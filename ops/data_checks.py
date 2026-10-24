"""
ops/data_checks.py
------------------
The "basic checks a professional would run" on the SQLite data. Read-only.

  BLOCK  = stops the pipeline (data is wrong or missing in a way that matters)
  WARN   = look at it, but the pipeline continues
  INFO   = context

  1. Completeness  - every expected trading day (weekday minus holiday calendar) has a row  [BLOCK]
  2. Unexpected    - a row on a weekend or listed holiday                                   [WARN]
  3. Freshness     - latest row is the latest trading day whose session has closed          [WARN]
  4. Calendar      - holiday calendar exists and covers every year present in the data      [BLOCK]
  5. OHLC logic    - high >= low, open/close inside [low, high], prices > 0                 [BLOCK]
  6. Plausibility  - values inside sane ranges, daily Nifty move not absurd                 [BLOCK]
  7. Daily move    - |nifty_change_pct| above 12% (points are never limited)                [BLOCK]
  8. Manual fields - how many older rows still have empty hand-entered fields               [INFO]
"""
import datetime as dt
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from ops import trading_calendar as cal

# (min, max) sane bounds. Deliberately wide: they catch unit/typo errors, not opinions.
RANGES = {
    "nifty_open": (5000, 60000), "nifty_high": (5000, 60000), "nifty_low": (5000, 60000),
    "nifty_close": (5000, 60000), "vix_close": (3, 100), "brent_crude": (10, 250),
    "usd_inr": (40, 150), "us_10y_yield": (0, 12), "pcr_value": (0, 5),
}
MAX_DAILY_NIFTY_MOVE_PCT = 12.0
MANUAL_FIELDS = ["fii_equity_cr", "dii_equity_cr", "advance_count", "decline_count", "tomorrow_bias"]


def _today_ist():
    return dt.datetime.now(ZoneInfo(config.MARKET_TIMEZONE))


def run_checks(conn, now=None):
    """Return list of (level, message)."""
    now = now or _today_ist()
    out = []
    rows = conn.execute("SELECT * FROM daily_data ORDER BY date").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM daily_data LIMIT 0").description]
    recs = [dict(zip(cols, r)) for r in rows]
    if not recs:
        return [("BLOCK", "daily_data is empty")]
    have = {dt.date.fromisoformat(r["date"]): r for r in recs}
    first, last = min(have), max(have)

    holidays, problems, years = cal.load_calendar()
    for p in problems:
        out.append(("BLOCK" if "IGNORED" in p else "WARN", f"calendar: {p}"))
    missing_years = sorted({d.year for d in have} - years)
    if missing_years:
        out.append(("BLOCK", f"calendar: no holidays listed for {missing_years}; gap checks are unreliable. "
                             "Add that year to nse_holidays.csv"))

    # 1. completeness / 2. unexpected rows
    for d in cal.expected_trading_days(first, last, holidays):
        if d not in have:
            out.append(("BLOCK", f"{d} ({d:%a}) is an expected trading day but has no row"))
    for d in sorted(have):
        if d.weekday() >= 5:
            out.append(("WARN", f"{d} is a {d:%A} but has a row"))
        elif d in holidays:
            out.append(("WARN", f"{d} has a row but is listed as a holiday ({holidays[d]})"))

    # 3. freshness
    after_close = (now.hour, now.minute) >= config.MARKET_CLOSE_TIME
    want = cal.last_expected_trading_day(now.date(), holidays, after_close)
    if last < want:
        out.append(("WARN", f"latest row is {last}; latest closed trading day is {want}"))

    # 5 & 6. OHLC logic + ranges
    for r in recs:
        d = r["date"]
        for name, (o, h, l, c) in {"nifty": ("nifty_open", "nifty_high", "nifty_low", "nifty_close"),
                                    "vix": ("vix_open", "vix_high", "vix_low", "vix_close")}.items():
            v = [r[o], r[h], r[l], r[c]]
            if all(isinstance(x, (int, float)) for x in v):
                if min(v) <= 0 or v[1] < v[2] or v[1] < max(v[0], v[3]) or v[2] > min(v[0], v[3]):
                    out.append(("BLOCK", f"{d} {name} OHLC is inconsistent: {v}"))
        for col, (lo, hi) in RANGES.items():
            x = r.get(col)
            if isinstance(x, (int, float)) and not lo <= x <= hi:
                out.append(("BLOCK", f"{d} {col}={x} outside plausible range {lo}-{hi}"))

    # 7. daily move. The limit applies to the PERCENTAGE (nifty_change_pct).
    #    nifty_change_pts is an index-point move and can legitimately be any size,
    #    so it is never range-checked or compared.
    for r in recs:
        pct = r["nifty_change_pct"]
        if isinstance(pct, (int, float)) and abs(pct) > MAX_DAILY_NIFTY_MOVE_PCT:
            out.append(("BLOCK", f"{r['date']} nifty_change_pct={pct} exceeds +/-{MAX_DAILY_NIFTY_MOVE_PCT}% "
                                 "- typo, wrong unit or missing day?"))

    # 8. manual fields
    cutoff = last - dt.timedelta(days=5)
    old = [r for r in recs if dt.date.fromisoformat(r["date"]) < cutoff]
    for f in MANUAL_FIELDS:
        n = sum(1 for r in old if r[f] is None)
        if n:
            out.append(("INFO", f"{n} of {len(old)} older rows have empty {f}"))
    return out


def main(db_path=None, now=None) -> int:
    conn = sqlite3.connect(f"file:{Path(db_path or config.DB_PATH)}?mode=ro", uri=True)
    try:
        findings = run_checks(conn, now)
    finally:
        conn.close()
    print("=" * 60 + "\nPROFESSIONAL DATA CHECKS\n" + "=" * 60)
    for level in ("BLOCK", "WARN", "INFO"):
        for lv, msg in findings:
            if lv == level:
                print(f"  [{lv}] {msg}")
    blocks = sum(1 for lv, _ in findings if lv == "BLOCK")
    warns = sum(1 for lv, _ in findings if lv == "WARN")
    print(f"\n  {blocks} blocking, {warns} warning(s).")
    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
