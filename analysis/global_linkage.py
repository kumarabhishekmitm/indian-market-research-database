"""
Step 16 (revised): Global linkage analysis.

Percentage-change fields (us_sp500_pct, us_nasdaq_pct, gift_nifty_pct) are
correlated directly against nifty_change_pct, since both sides are already
daily % changes.

Price-LEVEL fields (brent_crude, usd_inr, us_10y_yield) are first converted
to their own period-over-period % change (vs. the previous tracked row),
then correlated — comparing change-to-change, not level-to-change.

Gaps of more than 4 calendar days between consecutive market_vibe rows are
flagged, since a "change" computed across a gap isn't a true daily change.

Read-only — never modifies the database.
"""

import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

PCT_CHANGE_COLUMNS = ["us_sp500_pct", "us_nasdaq_pct", "gift_nifty_pct"]
LEVEL_COLUMNS = ["brent_crude", "usd_inr", "us_10y_yield"]

MIN_RELIABLE_SAMPLE_SIZE = 30
MAX_NORMAL_GAP_DAYS = 4


def pearson_correlation(x, y):
    n = len(x)
    if n < 2:
        return None
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


def compute_pct_change_series(dates, values):
    """
    Given ordered dates and values, compute % change from each row to the
    previous row. Returns a list of (date, pct_change, gap_days) for rows
    where both this value and the previous value exist.
    """
    results = []
    prev_date = None
    prev_value = None

    for date_str, value in zip(dates, values):
        current_date = datetime.strptime(date_str, "%Y-%m-%d")
        if prev_value is not None and value is not None and prev_value != 0:
            pct_change = (value - prev_value) / prev_value * 100
            gap_days = (current_date - prev_date).days
            results.append((date_str, pct_change, gap_days))
        if value is not None:
            prev_date = current_date
            prev_value = value

    return results


def main():
    conn = sqlite3.connect(DB_PATH)

    all_cols = PCT_CHANGE_COLUMNS + LEVEL_COLUMNS
    query = f"""
        SELECT m.date, {", ".join("m." + c for c in all_cols)}, d.nifty_change_pct
        FROM market_vibe m
        JOIN daily_data d ON m.date = d.date
        ORDER BY m.date;
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    print(f"Joined rows (same-date match between market_vibe and daily_data): {len(rows)}")
    if len(rows) < MIN_RELIABLE_SAMPLE_SIZE:
        print(
            f"WARNING: sample size ({len(rows)}) is below {MIN_RELIABLE_SAMPLE_SIZE}. "
            "Correlations below are exploratory only — NOT statistically reliable "
            "(see project rule #22)."
        )
    print()

    dates = [r[0] for r in rows]
    nifty_pct_by_date = {r[0]: r[-1] for r in rows}

    # --- Part 1: columns already stored as % change ---
    print("--- Fields already stored as % change (direct correlation) ---")
    for i, col_name in enumerate(PCT_CHANGE_COLUMNS, start=1):
        col_values = [r[i] for r in rows]
        paired = [(x, y) for x, y in zip(col_values, [r[-1] for r in rows]) if x is not None and y is not None]
        if len(paired) < 2:
            print(f"{col_name}: not enough data (n={len(paired)})")
            continue
        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]
        corr = pearson_correlation(xs, ys)
        corr_str = f"{corr:.3f}" if corr is not None else "undefined"
        print(f"{col_name} vs nifty_change_pct: correlation = {corr_str}  (n={len(paired)})")

    # --- Part 2: price-level columns converted to % change first ---
    print("\n--- Price-level fields (converted to period-over-period % change first) ---")
    offset = 1 + len(PCT_CHANGE_COLUMNS)
    for i, col_name in enumerate(LEVEL_COLUMNS, start=offset):
        col_values = [r[i] for r in rows]
        change_series = compute_pct_change_series(dates, col_values)

        # Flag unusual gaps
        unusual_gaps = [(d, g) for d, _, g in change_series if g > MAX_NORMAL_GAP_DAYS]
        if unusual_gaps:
            for d, g in unusual_gaps:
                print(f"  NOTE: {col_name} change ending {d} spans {g} calendar days (gap in tracked data)")

        xs = [pct for _, pct, _ in change_series]
        ys = [nifty_pct_by_date[d] for d, _, _ in change_series if nifty_pct_by_date.get(d) is not None]
        # Re-pair carefully in case nifty value is missing for a date
        paired = [
            (pct, nifty_pct_by_date[d]) for d, pct, _ in change_series
            if nifty_pct_by_date.get(d) is not None
        ]

        if len(paired) < 2:
            print(f"{col_name} (% change): not enough data (n={len(paired)})")
            continue

        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]
        corr = pearson_correlation(xs, ys)
        corr_str = f"{corr:.3f}" if corr is not None else "undefined"
        print(f"{col_name} (% change) vs nifty_change_pct: correlation = {corr_str}  (n={len(paired)})")


if __name__ == "__main__":
    main()