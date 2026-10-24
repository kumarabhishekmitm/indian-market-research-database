"""The pre-prune gate must catch data that pruning would destroy."""

import sqlite3

from helpers import daily_row, make_db, make_workbook, query
from ingest.migrate_from_excel import main as migrate
from ops.reconcile import find_problems

# 17 distinct dates with retention 15 -> the 2 oldest (n=0,1) would be pruned.
ROWS = [daily_row(n) for n in range(17)]


def setup(tmp_path, rows=ROWS):
    wb = make_workbook(tmp_path / "wb.xlsx", daily=rows)
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=wb)
    return db, wb


def test_clean_state_is_safe_to_prune(tmp_path):
    db, wb = setup(tmp_path)
    assert find_problems(db, wb) == []


def test_row_missing_from_database_blocks_prune(tmp_path):
    db, wb = setup(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM daily_data WHERE date = '2026-01-05'")
    conn.commit(); conn.close()
    problems = find_problems(db, wb)
    assert len(problems) == 1 and "not in database" in problems[0]


def test_value_filled_in_excel_but_null_in_db_blocks_prune(tmp_path):
    db, wb = setup(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE daily_data SET nifty_high = NULL WHERE date = '2026-01-05'")
    conn.commit(); conn.close()
    assert any("nifty_high" in p for p in find_problems(db, wb))


def test_changed_value_blocks_prune(tmp_path):
    db, wb = setup(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE daily_data SET nifty_close = 1 WHERE date = '2026-01-06'")
    conn.commit(); conn.close()
    assert any("nifty_close" in p for p in find_problems(db, wb))


def test_rows_inside_retention_window_are_not_checked(tmp_path):
    db, wb = setup(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM daily_data WHERE date = (SELECT MAX(date) FROM daily_data)")
    conn.commit(); conn.close()
    assert find_problems(db, wb) == []  # newest row is kept by prune, so no risk
