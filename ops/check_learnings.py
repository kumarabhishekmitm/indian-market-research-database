import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM learnings;").fetchone()[0]
actionable_breakdown = conn.execute(
    "SELECT actionable, COUNT(*) FROM learnings GROUP BY actionable;"
).fetchall()
sample = conn.execute("SELECT * FROM learnings ORDER BY date LIMIT 2;").fetchall()
issues = conn.execute(
    "SELECT source_row_number, issue_description FROM data_quality_issues WHERE source_sheet = 'Learnings';"
).fetchall()
conn.close()

print(f"Total rows in learnings: {count}")
print(f"\nBreakdown by actionable (1=True, 0=False, None=blank):")
for val, cnt in actionable_breakdown:
    print(f"  {val}: {cnt}")

print(f"\nSample rows:")
for r in sample:
    print(f"  {r}")

print(f"\nData quality issues logged for learnings: {len(issues)}")
for row_num, desc in issues:
    print(f"  Row {row_num}: {desc}")