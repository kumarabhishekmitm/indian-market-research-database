"""
ops/validate_db.py
------------------
Validates the database for internal consistency. Read-only: never modifies data.

Exit code:
    0 = no blocking problems
    1 = blocking problems found

Blocking problems (the pipeline must not prune the workbook while these exist):
    - PRAGMA integrity_check fails
    - PRAGMA foreign_key_check reports violations
    - daily_data is empty
    - sectors rows whose date has no matching daily_data row
    - events rows whose date has no matching daily_data row
    - any rows in data_quality_issues (a workbook row could not be loaded)

Informational only (never blocks):
    - trading days with no market_vibe entry
    - weekdays missing from daily_data that are not in confirmed_holidays.json
"""

import datetime as dt
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

DB_PATH = config.DB_PATH


def _load_holidays_with_problems():
    # Local import: the state helper lives next to the updater.
    sys.path.insert(0, str(config.STATE_DIR))
    try:
        import holiday_state
        return holiday_state.load_with_problems(config.CONFIRMED_HOLIDAYS_FILE)
    finally:
        sys.path.pop(0)


def _load_holidays():
    return _load_holidays_with_problems()[0]


def check_holiday_file(conn, holidays=None, problems=None) -> int:
    """Holiday-file health. Returns the number of BLOCKING problems.

    Blocking: an entry that could not be parsed (it is being ignored, so the
    gap check below would misreport that day).
    Informational: a holiday that also has a daily_data row, a weekend date,
    or an entry that parses but is not written as YYYY-MM-DD.
    """
    header("CONFIRMED HOLIDAYS FILE")
    if holidays is None:
        holidays, problems = _load_holidays_with_problems()
    blocking = 0
    for p in problems or []:
        if "IGNORED" in p or "could not be read" in p or "must contain" in p:
            print(f"  [PROBLEM] {p}")
            blocking += 1
        else:
            print(f"  [CHECK] {p}")
    have = {r[0] for r in conn.execute("SELECT date FROM daily_data")}
    for h in sorted(holidays):
        if h.isoformat() in have:
            print(f"  [CHECK] {h} is listed as a holiday but daily_data HAS a row for it.")
        if h.weekday() >= 5:
            print(f"  [CHECK] {h} ({h:%a}) is a weekend - it does not need to be in the file.")
    if not blocking:
        print(f"  {len(holidays)} holiday date(s) loaded.")
    return blocking


def header(title: str, leading_newline: bool = True):
    print(("\n" if leading_newline else "") + "=" * 60)
    print(title)
    print("=" * 60)


def check_row_counts(conn) -> int:
    """Prints table sizes. Returns 1 if daily_data is empty (blocking), else 0."""
    header("ROW COUNTS", leading_newline=False)
    tables = [
        "sector_list", "daily_data", "market_vibe",
        "sectors", "events", "learnings", "metadata",
        "data_quality_issues",
    ]
    counts = {}
    for table in tables:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        print(f"  {table}: {counts[table]} rows")

    if counts["daily_data"] == 0:
        print("  [PROBLEM] daily_data is empty.")
        return 1
    return 0


def check_orphan_dates(conn, table: str, label: str) -> int:
    """Rows in `table` whose date has no matching daily_data row. Returns number of orphan dates."""
    header(f"{label.upper()} WITH DATES NOT IN daily_data")
    rows = conn.execute(f"""
        SELECT DISTINCT t.date
        FROM {table} t
        LEFT JOIN daily_data d ON t.date = d.date
        WHERE d.date IS NULL
        ORDER BY t.date;
    """).fetchall()
    if not rows:
        print(f"  None found — all {label} dates have a matching trading day.")
        return 0
    for (date,) in rows:
        print(f"  [PROBLEM] {date} — appears in {table} but not in daily_data")
    return len(rows)


def check_missing_market_vibe_dates(conn):
    """Informational only: trading days with no market_vibe row."""
    header("TRADING DAYS WITH NO market_vibe ENTRY (informational)")
    rows = conn.execute("""
        SELECT d.date
        FROM daily_data d
        LEFT JOIN market_vibe m ON d.date = m.date
        WHERE m.date IS NULL
        ORDER BY d.date;
    """).fetchall()
    print(f"  {len(rows)} trading day(s) have no market_vibe entry (this may be expected — you started tracking market_vibe later).")


def check_data_quality_summary(conn) -> int:
    """Returns the total number of logged data-quality issues (all blocking)."""
    header("DATA QUALITY ISSUES SUMMARY")
    rows = conn.execute("""
        SELECT source_sheet, COUNT(*)
        FROM data_quality_issues
        GROUP BY source_sheet
        ORDER BY source_sheet;
    """).fetchall()
    if not rows:
        print("  No issues logged.")
        return 0
    total = 0
    for sheet, count in rows:
        print(f"  [PROBLEM] {sheet}: {count} issue(s) logged")
        total += count
    return total


NUMERIC_TEXT_OK = {"pcr_type", "emotional_state", "tomorrow_bias"}


def check_text_in_numeric_columns(conn) -> int:
    """SQLite lets text sit in a REAL column. Such a value (e.g. '') is not NULL,
    so the fill-the-blanks import can never replace it. Returns problem count."""
    header("TEXT STORED IN NUMERIC COLUMNS")
    problems = 0
    for table, key in (("daily_data", "date"), ("sectors", "sector_id")):
        for _, col, ctype, *_ in conn.execute(f"PRAGMA table_info({table})").fetchall():
            if col in (key, "date", "sector_name", "performance") or col in NUMERIC_TEXT_OK \
                    or ctype not in ("REAL", "INTEGER"):
                continue
            bad = conn.execute(
                f"SELECT {key}, quote({col}) FROM {table} WHERE typeof({col}) = 'text' ORDER BY {key}"
            ).fetchall()
            for k, shown in bad:
                print(f"  [PROBLEM] {table} {key}={k} {col} holds text {shown}. Fix (after a backup): "
                      f"UPDATE {table} SET {col} = NULL WHERE {key} = '{k}';")
                problems += 1
    sec_type = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(sectors)")}.get("sector_return_pct")
    if sec_type != "REAL":
        print(f"  [CHECK] sectors.sector_return_pct is still {sec_type}. "
              "Run: python ops/convert_sector_return_to_real.py")
    if not problems:
        print("  None found.")
    return problems


def check_sqlite_integrity(conn) -> int:
    """PRAGMA integrity_check + foreign_key_check. Returns number of problems."""
    header("SQLITE INTEGRITY AND FOREIGN KEYS")
    problems = 0
    result = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    if result == "ok":
        print("  integrity_check: ok")
    else:
        print(f"  [PROBLEM] integrity_check: {result}")
        problems += 1
    violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    if not violations:
        print("  foreign_key_check: no violations")
    for table, rowid, parent, _ in violations:
        print(f"  [PROBLEM] {table} rowid {rowid} references missing row in {parent}")
        problems += 1
    return problems


def check_weekday_gaps(conn, holidays=None):
    """Informational: weekdays between first and last date with no daily_data row."""
    header("WEEKDAYS MISSING FROM daily_data (informational)")
    holidays = _load_holidays() if holidays is None else holidays
    have = {dt.date.fromisoformat(r[0]) for r in conn.execute("SELECT date FROM daily_data")}
    if not have:
        print("  (no data)")
        return []
    day, last, gaps = min(have), max(have), []
    while day <= last:
        if day.weekday() < 5 and day not in have and day not in holidays:
            gaps.append(day)
        day += dt.timedelta(days=1)
    if not gaps:
        print("  None - every weekday is either present or a confirmed holiday.")
    for g in gaps:
        print(f"  [CHECK] {g} ({g:%a}) has no row and is not in confirmed_holidays.json "
              "- holiday or missing data? Add it to the holiday file if it was a holiday.")
    return gaps


def main(db_path=None) -> int:
    path = Path(db_path or DB_PATH)
    # Read-only URI: validation can never modify (or accidentally create) the DB.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        problems = 0
        problems += check_sqlite_integrity(conn)
        problems += check_row_counts(conn)
        problems += check_text_in_numeric_columns(conn)
        problems += check_orphan_dates(conn, "sectors", "sectors")
        problems += check_orphan_dates(conn, "events", "events")
        check_missing_market_vibe_dates(conn)
        problems += check_holiday_file(conn)
        check_weekday_gaps(conn)
        problems += check_data_quality_summary(conn)
    finally:
        conn.close()

    header("RESULT")
    if problems:
        print(f"  [FAIL] {problems} blocking problem(s) found. Fix them before pruning the workbook.")
        return 1
    print("  [OK] No blocking problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
