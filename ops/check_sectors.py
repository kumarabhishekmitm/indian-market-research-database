import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM sectors;").fetchone()[0]
null_pct_count = conn.execute(
    "SELECT COUNT(*) FROM sectors WHERE sector_return_pct IS NULL;"
).fetchone()[0]
sample = conn.execute("SELECT * FROM sectors ORDER BY date, sector_id LIMIT 3;").fetchall()
issues = conn.execute(
    "SELECT source_row_number, issue_description FROM data_quality_issues WHERE source_sheet = 'sectors' ORDER BY source_row_number;"
).fetchall()
conn.close()

print(f"Total rows in sectors: {count}")
print(f"Rows with NULL sector_return_pct (was 'NA' in Excel): {null_pct_count}")
print("\nSample rows:")
for r in sample:
    print(f"  {r}")

print(f"\nData quality issues logged for sectors: {len(issues)}")
for row_num, desc in issues:
    print(f"  Row {row_num}: {desc}")