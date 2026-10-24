"""Regression tests for the Excel -> SQLite validation problems:

  * one malformed entry in confirmed_holidays.json must not erase the others
  * dates written as text / date objects / year-first slashes must import
  * text in a numeric Excel cell must be logged, not silently stored
  * the pre-migration Excel check must catch what the import would mangle
"""

import datetime as dt
import json
import sqlite3

import config
import holiday_state
from helpers import daily_row, day, make_db, make_workbook, query
from ingest.migrate_from_excel import main as migrate, to_iso_date
from ops import validate_db, validate_excel


# ---------------------------------------------------------------- holidays
def test_one_bad_holiday_entry_does_not_wipe_the_good_ones(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"confirmed_holidays": ["2026-09-14", "2026-10-32", "2026-10-20"]}))
    good, problems = holiday_state.load_with_problems(f)
    assert good == {dt.date(2026, 9, 14), dt.date(2026, 10, 20)}
    assert any("2026-10-32" in p and "IGNORED" in p for p in problems)


def test_unpadded_holiday_date_is_accepted_but_flagged(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"confirmed_holidays": ["2026-10-2"]}))
    good, problems = holiday_state.load_with_problems(f)
    assert good == {dt.date(2026, 10, 2)}
    assert problems and "2026-10-02" in problems[0]


def test_damaged_holiday_file_is_reported_not_silent(tmp_path):
    f = tmp_path / "h.json"
    f.write_text("{ not json")
    good, problems = holiday_state.load_with_problems(f)
    assert good == set() and problems


def test_shipped_holiday_file_is_clean():
    good, problems = holiday_state.load_with_problems(config.CONFIRMED_HOLIDAYS_FILE)
    assert problems == [] and good


def test_validate_db_blocks_on_unreadable_holiday_entry(tmp_path):
    db = make_db(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    assert validate_db.check_holiday_file(conn, holidays=set(), problems=["entry 'x' is not a valid date and was IGNORED"]) == 1
    assert validate_db.check_holiday_file(conn, holidays=set(), problems=["entry '2026-10-2' accepted but should be written 2026-10-02"]) == 0
    conn.close()


# ------------------------------------------------------------------- dates
def test_to_iso_date_accepts_the_formats_people_really_type():
    for v in [dt.datetime(2026, 8, 31, 20, 35), dt.date(2026, 8, 31), "2026-08-31", " 2026-08-31 ",
              "2026-8-31", "2026/08/31", "2026-08-31 00:00:00"]:
        assert to_iso_date(v) == "2026-08-31", v


def test_to_iso_date_refuses_to_guess_ambiguous_values():
    for v in ["31-08-2026", "03/04/2026", 46265, "TBD", "", None, "2026-02-30"]:
        assert to_iso_date(v) is None, v


def test_mixed_text_and_real_dates_import_without_issues(tmp_path):
    wb = make_workbook(tmp_path / "wb.xlsx", daily=[
        daily_row(0, date="2026-01-05"), daily_row(1, date=day(1)), daily_row(2, date="2026/01/07")])
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=wb)
    assert [r[0] for r in query(db, "SELECT date FROM daily_data ORDER BY date")] == \
        ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert query(db, "SELECT COUNT(*) FROM data_quality_issues") == [(0,)]


# ---------------------------------------------------------- numeric typing
def test_text_in_numeric_cell_is_logged_and_never_stored(tmp_path):
    wb = make_workbook(tmp_path / "wb.xlsx", daily=[daily_row(0, fii_equity_cr="TBD", advance_count="17")])
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=wb)
    assert query(db, "SELECT typeof(fii_equity_cr), typeof(advance_count) FROM daily_data") == [("null", "integer")]
    assert query(db, "SELECT COUNT(*) FROM data_quality_issues WHERE issue_description LIKE '%fii_equity_cr%'") == [(1,)]


def test_validate_db_flags_text_stuck_in_numeric_column(tmp_path):
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=make_workbook(tmp_path / "wb.xlsx", daily=[daily_row(0)]))
    conn = sqlite3.connect(db)
    conn.execute("UPDATE daily_data SET advance_decline_ratio = ''")
    conn.commit()
    assert validate_db.check_text_in_numeric_columns(conn) == 1
    conn.close()


# --------------------------------------------------- pre-migration checker
def test_validate_excel_passes_clean_and_catches_bad_workbooks(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "CONFIRMED_HOLIDAYS_FILE", tmp_path / "none.json")
    clean = make_workbook(tmp_path / "ok.xlsx", daily=[daily_row(0), daily_row(1)])
    assert validate_excel.main(clean) == 0

    bad = make_workbook(tmp_path / "bad.xlsx", daily=[
        daily_row(0), daily_row(0),                              # duplicate date
        daily_row(1, date="31-01-2026"),                         # day-first text
        daily_row(2, vix_close="n/a?"),                          # text in numeric cell
        daily_row(3, nifty_high=1.0),                            # high below low
    ])
    assert validate_excel.main(bad) == 1
    out = capsys.readouterr().out
    for needle in ("duplicate date", "unreadable date", "vix_close", "impossible OHLC"):
        assert needle in out, needle


def test_validate_excel_warns_on_time_of_day_and_holiday_conflict(tmp_path, capsys, monkeypatch):
    h = tmp_path / "h.json"
    h.write_text(json.dumps({"confirmed_holidays": [day(1).date().isoformat()]}))
    monkeypatch.setattr(config, "CONFIRMED_HOLIDAYS_FILE", h)
    wb = make_workbook(tmp_path / "w.xlsx", daily=[
        daily_row(0, date=day(0).replace(hour=20, minute=35)), daily_row(1)])
    assert validate_excel.main(wb) == 0
    out = capsys.readouterr().out
    assert "time of day" in out and "confirmed_holidays.json" in out
