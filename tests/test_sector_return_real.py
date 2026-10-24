import sqlite3

import pytest

from helpers import daily_row, make_db, make_workbook, query
from ingest.migrate_from_excel import main as migrate
from ops import convert_sector_return_to_real as conv, validate_db, validate_excel

OLD_SCHEMA = """
CREATE TABLE sectors (
    sector_id INTEGER PRIMARY KEY, date TEXT NOT NULL, sector_name TEXT NOT NULL,
    performance TEXT, sector_return_pct TEXT,
    FOREIGN KEY (sector_name) REFERENCES sector_list(sector_name))"""


def old_style_db(tmp_path, values):
    db = make_db(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE sectors")
    conn.execute(OLD_SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO sector_list VALUES (?)", [("Nifty Bank",), ("Nifty IT",)])
    for i, v in enumerate(values, start=1):
        conn.execute("INSERT INTO sectors VALUES (?,?,?,?,?)", (i, "2026-01-05", "Nifty Bank", "TOP_GAINER", v))
    conn.commit()
    conn.close()
    return db


def test_new_schema_is_real():
    assert "sector_return_pct   REAL" in open("ingest/schema.sql").read()


def test_conversion_keeps_every_row_and_value(tmp_path):
    db = old_style_db(tmp_path, ["-0.91", "0.73", None, "2", "-0.6"])
    before = query(db, "SELECT sector_id, date, sector_name, performance FROM sectors ORDER BY sector_id")
    assert "converted" in conv.convert(db)
    assert query(db, "SELECT sector_id, date, sector_name, performance FROM sectors ORDER BY sector_id") == before
    assert query(db, "SELECT sector_return_pct FROM sectors ORDER BY sector_id") == [(-0.91,), (0.73,), (None,), (2.0,), (-0.6,)]
    assert query(db, "SELECT COUNT(*) FROM sectors WHERE typeof(sector_return_pct)='text'") == [(0,)]
    assert [r[2] for r in query(db, "PRAGMA table_info(sectors)")][4] == "REAL"


def test_conversion_is_idempotent_and_dry_run_changes_nothing(tmp_path):
    db = old_style_db(tmp_path, ["1.5"])
    assert conv.convert(db, dry_run=True).startswith("DRY RUN")
    assert query(db, "SELECT typeof(sector_return_pct) FROM sectors") == [("text",)]
    conv.convert(db)
    assert conv.convert(db) == "already REAL - nothing to do"


def test_conversion_aborts_untouched_on_non_numeric(tmp_path):
    db = old_style_db(tmp_path, ["1.5", "N/A?"])
    with pytest.raises(SystemExit):
        conv.convert(db)
    assert query(db, "SELECT sector_return_pct FROM sectors ORDER BY sector_id") == [("1.5",), ("N/A?",)]


def test_import_stores_numbers_and_logs_junk(tmp_path):
    sectors = [(1, "2026-01-05", "Nifty Bank", "TOP_GAINER", "1.25"),
               (2, "2026-01-05", "Nifty IT", "TOP_LOSER", "NA"),
               (3, "2026-01-06", "Nifty IT", "TOP_LOSER", "oops")]
    wb = make_workbook(tmp_path / "w.xlsx", daily=[daily_row(0), daily_row(1)], sectors=sectors)
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=wb)
    assert query(db, "SELECT sector_id, typeof(sector_return_pct) FROM sectors ORDER BY sector_id") == \
        [(1, "real"), (2, "null"), (3, "null")]
    assert query(db, "SELECT COUNT(*) FROM data_quality_issues WHERE issue_description LIKE '%sector_return_pct%'") == [(1,)]


def test_validators_catch_junk_return(tmp_path, capsys):
    sectors = [(1, "2026-01-05", "Nifty Bank", "TOP_GAINER", "oops")]
    wb = make_workbook(tmp_path / "w.xlsx", daily=[daily_row(0)], sectors=sectors)
    assert validate_excel.main(wb) == 1
    assert "sector_return_pct" in capsys.readouterr().out


def test_validate_db_flags_text_in_sectors_and_old_column_type(tmp_path, capsys):
    db = old_style_db(tmp_path, ["1.5"])
    conn = sqlite3.connect(db)
    validate_db.check_text_in_numeric_columns(conn)
    assert "still TEXT" in capsys.readouterr().out
    conn.close()
