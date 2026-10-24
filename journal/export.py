"""
Step 20 (revised): Export the last N trading days from all tables to CSV.

Usage:
    python export.py           (defaults to last 7 trading days)
    python export.py 14        (last 14 trading days instead)

"Trading days" are determined from the actual dates present in
daily_data — not calendar days — so weekends/holidays are naturally
skipped since they were never trading days to begin with.

Read-only on the database — only creates new CSV files.
"""

import csv
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "market.db"
EXPORT_DIR = Path(__file__).parent / "exports"

TABLES = ["daily_data", "market_vibe", "sectors", "events", "learnings"]

DEFAULT_TRADING_DAYS = 7


def get_last_n_trading_days(conn, n):
    rows = conn.execute(
        "SELECT DISTINCT date FROM daily_data ORDER BY date DESC LIMIT ?;",
        (n,),
    ).fetchall()
    dates = [r[0] for r in rows]
    dates.sort()  # chronological order, oldest to newest
    return dates


def export_table(conn, table_name, trading_dates, start_date, end_date):
    placeholders = ", ".join("?" for _ in trading_dates)
    cursor = conn.execute(
        f"SELECT * FROM {table_name} WHERE date IN ({placeholders}) ORDER BY date;",
        trading_dates,
    )
    rows = cursor.fetchall()
    column_names = [description[0] for description in cursor.description]

    filename = EXPORT_DIR / f"{table_name}_{start_date}_to_{end_date}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        writer.writerows(rows)

    return len(rows), filename


def main():
    n = DEFAULT_TRADING_DAYS
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
            if n <= 0:
                raise ValueError
        except ValueError:
            print(f"Invalid argument {sys.argv[1]!r} — expected a positive whole number.")
            return

    conn = sqlite3.connect(DB_PATH)
    trading_dates = get_last_n_trading_days(conn, n)

    if not trading_dates:
        print("No trading days found in daily_data.")
        conn.close()
        return

    start_date, end_date = trading_dates[0], trading_dates[-1]
    print(f"Exporting last {len(trading_dates)} trading day(s): {start_date} to {end_date}\n")

    EXPORT_DIR.mkdir(exist_ok=True)

    for table in TABLES:
        row_count, filename = export_table(conn, table, trading_dates, start_date, end_date)
        print(f"  {table}: {row_count} row(s) -> {filename.name}")

    conn.close()
    print(f"\nAll files saved to: {EXPORT_DIR}")


if __name__ == "__main__":
    main()