"""
Step 17 (final): Sector rotation analysis, two fixed windows.

Prints two tables every run:
  1. "Last 30 Days" (~20 trading days) — recent momentum
  2. "Last 6 Months" (~126 trading days) — longer trend

If less history exists than the window asks for, the full available
history is used instead, with a note explaining that.

Read-only — never modifies the database.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

WINDOWS = [
    ("LAST 30 DAYS (~20 trading days)", 20),
    ("LAST 6 MONTHS (~126 trading days)", 126),
]


def get_window_dates(conn, window_size):
    rows = conn.execute(
        "SELECT DISTINCT date FROM sectors ORDER BY date DESC LIMIT ?;",
        (window_size,),
    ).fetchall()
    return [r[0] for r in rows]


def print_table(conn, label, window_size):
    window_dates = get_window_dates(conn, window_size)
    available_days = len(window_dates)

    print("=" * 70)
    print(label)
    print("=" * 70)

    if available_days < window_size:
        print(f"(Requested {window_size} trading days, but only {available_days} "
              f"exist in the database — showing all available history instead.)")

    if not window_dates:
        print("No data available.")
        return

    print(f"Actual range shown: {min(window_dates)} to {max(window_dates)} "
          f"({available_days} trading day(s))\n")

    placeholders = ", ".join("?" for _ in window_dates)
    query = f"""
        SELECT
            sector_name,
            SUM(CASE WHEN performance = 'TOP_GAINER' THEN 1 ELSE 0 END) AS gainer_count,
            SUM(CASE WHEN performance = 'TOP_LOSER' THEN 1 ELSE 0 END) AS loser_count,
            COUNT(*) AS total_appearances,
            AVG(CASE WHEN sector_return_pct IS NOT NULL THEN CAST(sector_return_pct AS REAL) END) AS avg_return_pct,
            SUM(CASE WHEN sector_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_return_pct
        FROM sectors
        WHERE date IN ({placeholders})
        GROUP BY sector_name
        ORDER BY gainer_count DESC, loser_count ASC;
    """
    rows = conn.execute(query, window_dates).fetchall()

    print(f"{'Sector':<30} {'Gainer':>7} {'Loser':>7} {'Total':>7} {'AvgRet%':>9} {'(n)':>5}")
    print("-" * 70)

    total_gainers = total_losers = total_rows = 0
    for name, gainers, losers, total, avg_ret, n_ret in rows:
        avg_str = f"{avg_ret:.2f}" if avg_ret is not None else "n/a"
        print(f"{name:<30} {gainers:>7} {losers:>7} {total:>7} {avg_str:>9} {n_ret:>5}")
        total_gainers += gainers
        total_losers += losers
        total_rows += total

    print("-" * 70)
    print(f"{'TOTALS':<30} {total_gainers:>7} {total_losers:>7} {total_rows:>7}")
    print()


def main():
    conn = sqlite3.connect(DB_PATH)
    for label, window_size in WINDOWS:
        print_table(conn, label, window_size)
    conn.close()
    print("Note: 'AvgRet%' is averaged only over rows where sector_return_pct")
    print("was an actual number in Excel (not 'NA').")


if __name__ == "__main__":
    main()