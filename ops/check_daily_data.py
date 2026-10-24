import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM daily_data;").fetchone()[0]
first = conn.execute("SELECT * FROM daily_data ORDER BY date ASC LIMIT 1;").fetchone()
last = conn.execute("SELECT * FROM daily_data ORDER BY date DESC LIMIT 1;").fetchone()
issues = conn.execute("SELECT COUNT(*) FROM data_quality_issues WHERE source_sheet = 'DailyData';").fetchone()[0]
conn.close()

print(f"Total rows in daily_data: {count}")
print(f"First row: {first}")
print(f"Last row: {last}")
print(f"Data quality issues logged for DailyData: {issues}")