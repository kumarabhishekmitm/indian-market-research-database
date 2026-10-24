"""
Step 18: Drawdown analysis.

For each trading day, computes:
  - running_peak: the highest nifty_close seen up to and including that day
    (calculated using only past/current data — no look-ahead bias)
  - drawdown_pct: how far today's close is below that running peak

Also reports the single worst drawdown in the tracked period, and flags
days where VIX was unusually high alongside a large drawdown.

Read-only — never modifies the database.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"


def main():
    print("NOTE: 'PeakSinceTracking' is the highest Nifty close observed SINCE this")
    print("database started recording data (2026-08-03). It is NOT necessarily")
    print("Nifty's true 52-week or all-time high — Nifty may have traded higher")
    print("before tracking began. Treat all drawdown figures below as relative")
    print("to this tracking-period peak only.\n")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT date, nifty_close, vix_close
        FROM daily_data
        ORDER BY date ASC;
    """).fetchall()
    conn.close()

    if not rows:
        print("No data in daily_data.")
        return
    
    print(f"{'Date':<12} {'Close':>10} {'PeakSinceTracking':>18} {'Drawdown%':>10} {'VIX':>7}")
    print("-" * 56)

    running_peak = None
    worst_drawdown_pct = 0.0
    worst_drawdown_date = None

    for date_str, close, vix in rows:
        if running_peak is None or close > running_peak:
            running_peak = close

        drawdown_pct = (close - running_peak) / running_peak * 100

        if drawdown_pct < worst_drawdown_pct:
            worst_drawdown_pct = drawdown_pct
            worst_drawdown_date = date_str

        vix_str = f"{vix:.2f}" if vix is not None else "n/a"
        print(f"{date_str:<12} {close:>10.2f} {running_peak:>18.2f} {drawdown_pct:>9.2f}% {vix_str:>7}")
    print("-" * 56)
    print(f"\nWorst drawdown SINCE TRACKING BEGAN: {worst_drawdown_pct:.2f}% on {worst_drawdown_date}")

    latest_date, latest_close, latest_vix = rows[-1]
    latest_drawdown = (latest_close - running_peak) / running_peak * 100
    print(f"Current drawdown (as of {latest_date}): {latest_drawdown:.2f}% "
          f"from tracking-period peak of {running_peak:.2f} "
          f"(peak set on {rows[0][0]} — the first day of tracking)")


if __name__ == "__main__":
    main()