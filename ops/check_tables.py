import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [row[0] for row in cursor.fetchall()]
conn.close()

print("Tables in database:")
for t in tables:
    print(f"  - {t}")