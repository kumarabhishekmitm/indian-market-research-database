import datetime as dt
import sqlite3

from helpers import daily_row, make_db, make_workbook
from ingest.migrate_from_excel import main as migrate
from ops import validate_db


def build(tmp_path, rows):
    wb = make_workbook(tmp_path / "wb.xlsx", daily=rows)
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=wb)
    return db


def test_clean_database_passes(tmp_path):
    db = build(tmp_path, [daily_row(0), daily_row(1)])
    assert validate_db.main(db) == 0


def test_foreign_key_violation_is_blocking(tmp_path):
    db = build(tmp_path, [daily_row(0)])
    conn = sqlite3.connect(db)  # FK enforcement is off by default on this connection
    conn.execute("INSERT INTO sectors (date, sector_name) VALUES ('2026-01-05', 'Ghost Sector')")
    conn.commit()
    assert validate_db.check_sqlite_integrity(conn) >= 1
    conn.close()


def test_weekday_gap_reported_unless_confirmed_holiday(tmp_path):
    db = build(tmp_path, [daily_row(0), daily_row(2)])  # Mon, Wed -> Tuesday missing
    conn = sqlite3.connect(db)
    assert validate_db.check_weekday_gaps(conn, holidays=set()) == [dt.date(2026, 1, 6)]
    assert validate_db.check_weekday_gaps(conn, holidays={dt.date(2026, 1, 6)}) == []
    conn.close()


def test_validation_is_read_only(tmp_path):
    db = build(tmp_path, [daily_row(0)])
    before = db.read_bytes()
    validate_db.main(db)
    assert db.read_bytes() == before
