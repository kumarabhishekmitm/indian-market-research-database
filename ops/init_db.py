"""
ops/init_db.py
--------------
Apply ingest/schema.sql to create (or top up) the SQLite database.
Safe to re-run: schema.sql uses CREATE TABLE IF NOT EXISTS.
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

SCHEMA_PATH = PROJECT_ROOT / "ingest" / "schema.sql"


def main(db_path=None):
    db_path = Path(db_path or config.DB_PATH)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)
        conn.commit()
        print(f"Schema applied successfully to: {db_path}")
    except Exception as e:
        conn.rollback()
        print(f"FAILED to apply schema. Rolled back. Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
