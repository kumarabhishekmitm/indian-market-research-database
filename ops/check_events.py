import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM events;").fetchone()[0]
directions = conn.execute(
    "SELECT impact_direction, COUNT(*) FROM events GROUP BY impact_direction;"
).fetchall()
sample = conn.execute("SELECT * FROM events ORDER BY date LIMIT 2;").fetchall()
issues = conn.execute(
    "SELECT source_row_number, issue_description FROM data_quality_issues WHERE source_sheet = ?;",
    (SHEET_EVENTS := "Events_page ",)
).fetchall()
conn.close()

print(f"Total rows in events: {count}")
print(f"\nBreakdown by impact_direction:")
for direction, cnt in directions:
    print(f"  {direction}: {cnt}")

print(f"\nSample rows:")
for r in sample:
    print(f"  {r}")

print(f"\nData quality issues logged for events: {len(issues)}")
for row_num, desc in issues:
    print(f"  Row {row_num}: {desc}")