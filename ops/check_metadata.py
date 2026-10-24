import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT key, value, comment FROM metadata ORDER BY key;").fetchall()
issues = conn.execute(
    "SELECT source_row_number, issue_description FROM data_quality_issues WHERE source_sheet = 'Metadata';"
).fetchall()
conn.close()

print(f"Total rows in metadata: {len(rows)}")
for r in rows:
    print(f"  {r}")

print(f"\nData quality issues logged for Metadata: {len(issues)}")
for row_num, desc in issues:
    print(f"  Row {row_num}: {desc}")