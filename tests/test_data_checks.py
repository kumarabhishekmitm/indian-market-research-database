import datetime as dt
import json
import sqlite3
from zoneinfo import ZoneInfo

import pytest

import config
from helpers import daily_row as _row, day, make_db, make_workbook
from ingest.migrate_from_excel import main as migrate
from ops import data_checks, trading_calendar as cal

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def isolated_calendar(tmp_path, monkeypatch):
    csv_file = tmp_path / "h.csv"
    csv_file.write_text("date,occasion,source,verified\n2026-01-06,Test Holiday,test,no\n")
    monkeypatch.setattr(cal, "CALENDAR_CSV", csv_file)
    monkeypatch.setattr(config, "CONFIRMED_HOLIDAYS_FILE", tmp_path / "none.json")


def daily_row(n, **kw):
    base = dict(nifty_open=22000.0 + n, nifty_high=22100.0 + n, nifty_low=21900.0 + n, nifty_close=22050.0 + n)
    base.update(kw)
    return _row(n, **base)


def build(tmp_path, rows):
    db = make_db(tmp_path / "t.db")
    migrate(db_path=db, wb_path=make_workbook(tmp_path / "w.xlsx", daily=rows))
    return db


def levels(db, now):
    conn = sqlite3.connect(db)
    try:
        return data_checks.run_checks(conn, now)
    finally:
        conn.close()


NOW = dt.datetime(2026, 1, 9, 20, 0, tzinfo=IST)  # Fri evening, after close


def test_holiday_in_calendar_is_not_a_gap_but_a_real_gap_blocks(tmp_path, isolated_calendar):
    # day(0)=Mon 5 Jan, Tue 6 Jan is the holiday, day(2)=Wed 7, day(3)=Thu 8, day(4)=Fri 9
    ok = build(tmp_path, [daily_row(0), daily_row(2), daily_row(3), daily_row(4)])
    assert not [m for lv, m in levels(ok, NOW) if lv == "BLOCK"]

    tmp2 = tmp_path / "b"; tmp2.mkdir()
    gap = build(tmp2, [daily_row(0), daily_row(2), daily_row(4)])  # Thu 8 Jan missing
    blocks = [m for lv, m in levels(gap, NOW) if lv == "BLOCK"]
    assert any("2026-01-08" in m for m in blocks)


def test_row_on_a_holiday_warns(tmp_path, isolated_calendar):
    db = build(tmp_path, [daily_row(0), daily_row(1), daily_row(2), daily_row(3), daily_row(4)])
    assert any(lv == "WARN" and "2026-01-06" in m and "holiday" in m for lv, m in levels(db, NOW))


def test_stale_data_warns(tmp_path, isolated_calendar):
    db = build(tmp_path, [daily_row(0)])
    assert any(lv == "WARN" and "latest row" in m for lv, m in levels(db, NOW))


def test_year_missing_from_calendar_blocks(tmp_path, monkeypatch):
    f = tmp_path / "h.csv"; f.write_text("date,occasion,source,verified\n2025-01-26,Republic Day,t,no\n")
    monkeypatch.setattr(cal, "CALENDAR_CSV", f)
    monkeypatch.setattr(config, "CONFIRMED_HOLIDAYS_FILE", tmp_path / "none.json")
    db = build(tmp_path, [daily_row(0)])
    assert any(lv == "BLOCK" and "no holidays listed" in m for lv, m in levels(db, NOW))


def test_implausible_values_and_ohlc_block(tmp_path, isolated_calendar):
    db = build(tmp_path, [daily_row(0), daily_row(1, nifty_close=2210.0, nifty_high=2211.0, nifty_low=2205.0, nifty_open=2208.0)])
    blocks = " | ".join(m for lv, m in levels(db, NOW) if lv == "BLOCK")
    assert "outside plausible range" in blocks


def test_shipped_calendar_covers_2026_and_has_no_problems():
    holidays, problems, years = cal.load_calendar()
    assert 2026 in years and not problems
    assert dt.date(2026, 10, 20) in holidays


def test_last_expected_trading_day_skips_weekend_and_holiday():
    h = {dt.date(2026, 10, 2): "Gandhi Jayanti"}
    assert cal.last_expected_trading_day(dt.date(2026, 10, 4), h) == dt.date(2026, 10, 1)


def test_big_point_move_is_fine_but_big_percent_move_blocks(tmp_path, isolated_calendar):
    # 600-point move on ~22000 is ~2.7%: allowed, and the points column is never checked.
    ok = build(tmp_path, [daily_row(0), daily_row(1, nifty_change_pts=600.0, nifty_change_pct=2.7)])
    assert not [m for lv, m in levels(ok, NOW) if "nifty_change" in m]

    tmp2 = tmp_path / "b"; tmp2.mkdir()
    bad = build(tmp2, [daily_row(0), daily_row(1, nifty_change_pts=3000.0, nifty_change_pct=13.5)])
    assert any(lv == "BLOCK" and "nifty_change_pct=13.5" in m for lv, m in levels(bad, NOW))


def test_points_mismatch_is_no_longer_reported(tmp_path, isolated_calendar):
    db = build(tmp_path, [daily_row(0), daily_row(1, nifty_change_pts=5.0, nifty_change_pct=0.02)])
    assert not [m for lv, m in levels(db, NOW) if "nifty_change_pts" in m]
