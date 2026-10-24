import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM market_vibe;").fetchone()[0]
rows = conn.execute("SELECT * FROM market_vibe ORDER BY date;").fetchall()
issues = conn.execute(
    "SELECT source_row_number, issue_description FROM data_quality_issues WHERE source_sheet = 'Market_Vibe' ORDER BY source_row_number;"
).fetchall()
conn.close()

print(f"Total rows in market_vibe: {count}")
for r in rows:
    print(f"  {r}")

print(f"\nData quality issues logged for Market_Vibe: {len(issues)}")
for row_num, desc in issues:
    print(f"  Row {row_num}: {desc}")