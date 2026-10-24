"""
ops/trading_calendar.py
-----------------------
One place that answers "was this date supposed to be a trading day?".

Layers (a date is a holiday if ANY layer says so):
  1. data/excel_autofetch/nse_holidays.csv      - the calendar of record, one file
     per year-end review, copied from the NSE holiday circular (column
     `verified` = yes once you have checked it against nseindia.com).
  2. data/excel_autofetch/confirmed_holidays.json - ad-hoc additions (e.g. a
     surprise closure) that you confirmed by hand.
Special sessions (Muhurat etc.) are NOT holidays and need no entry: if the
exchange traded, the data row exists and the checks simply see a normal day.
"""
import csv
import datetime as dt
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

CALENDAR_CSV = config.STATE_DIR / "nse_holidays.csv"


def load_calendar(csv_path=None, json_path=None):
    """Return (holidays: dict[date, str reason], problems: list[str], years_covered: set[int])."""
    csv_path = Path(csv_path or CALENDAR_CSV)
    holidays, problems = {}, []
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            for n, row in enumerate(csv.DictReader(f), start=2):
                try:
                    d = dt.date.fromisoformat((row.get("date") or "").strip())
                except ValueError:
                    problems.append(f"{csv_path.name} line {n}: bad date {row.get('date')!r} - IGNORED")
                    continue
                holidays[d] = (row.get("occasion") or "holiday").strip()
    else:
        problems.append(f"{csv_path.name} not found - only confirmed_holidays.json is used")

    sys.path.insert(0, str(config.STATE_DIR))
    try:
        import holiday_state
        extra, hp = holiday_state.load_with_problems(Path(json_path or config.CONFIRMED_HOLIDAYS_FILE))
    finally:
        sys.path.pop(0)
    problems += [f"confirmed_holidays.json: {p}" for p in hp if "IGNORED" in p or "could not" in p]
    for d in extra:
        holidays.setdefault(d, "confirmed by hand")
    return holidays, problems, {d.year for d in holidays}


def expected_trading_days(start, end, holidays):
    day, out = start, []
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def last_expected_trading_day(today, holidays, after_close=True):
    """Most recent trading day whose session should be finished."""
    day = today if after_close else today - dt.timedelta(days=1)
    while day.weekday() >= 5 or day in holidays:
        day -= dt.timedelta(days=1)
    return day
