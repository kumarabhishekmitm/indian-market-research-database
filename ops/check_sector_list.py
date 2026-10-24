import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT sector_name FROM sector_list ORDER BY sector_name;").fetchall()
conn.close()

print(f"Total sectors: {len(rows)}")
for (name,) in rows:
    print(f"  - {name}")