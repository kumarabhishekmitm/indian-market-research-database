import sqlite3

from helpers import make_db, query

EXPECTED = {"daily_data", "market_vibe", "sectors", "events", "learnings",
            "metadata", "sector_list", "data_quality_issues"}


def test_init_db_creates_all_tables_in_a_temp_db(tmp_path):
    db = make_db(tmp_path / "t.db")
    tables = {r[0] for r in query(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= tables


def test_init_db_is_idempotent(tmp_path):
    db = make_db(tmp_path / "t.db")
    make_db(db)  # second run must not fail or drop anything
    assert query(db, "SELECT COUNT(*) FROM sector_list") == [(0,)]


def test_foreign_keys_are_enforced(tmp_path):
    db = make_db(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("INSERT INTO sectors (date, sector_name) VALUES ('2026-01-05', 'Not A Sector')")
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    finally:
        conn.close()
    assert raised
