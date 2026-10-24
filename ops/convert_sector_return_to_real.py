"""
ops/convert_sector_return_to_real.py
------------------------------------
ONE-TIME conversion of sectors.sector_return_pct from TEXT to REAL, so the
returns can be averaged, sorted and compared as numbers.

SQLite cannot change a column's type in place, so the table is rebuilt inside
ONE transaction. Safeguards:
  * a verified backup (ops/backup.py) is taken first, unless --no-backup
  * refuses to run if any value is not a plain number (nothing is touched)
  * keeps every sector_id, date, sector_name and performance exactly
  * afterwards proves: same row count, same ids, same NULL count, same sum
    (to 1e-9), no text left. Any mismatch rolls the whole thing back.
  * safe to re-run: does nothing once the column is already REAL
  * --dry-run reports what would happen and changes nothing

Usage:  python ops/convert_sector_return_to_real.py [--dry-run] [--no-backup]
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

NEW_TABLE_SQL = """
CREATE TABLE sectors_new (
    sector_id           INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,
    sector_name         TEXT NOT NULL,
    performance         TEXT,
    sector_return_pct   REAL,
    FOREIGN KEY (sector_name) REFERENCES sector_list(sector_name)
)"""


def _column_type(conn):
    return {r[1]: r[2] for r in conn.execute("PRAGMA table_info(sectors)")}.get("sector_return_pct")


def _as_number(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).strip().replace(",", ""))  # ValueError if not numeric


def convert(db_path, dry_run=False) -> str:
    conn = sqlite3.connect(db_path, isolation_level=None)  # manual transaction control
    try:
        if _column_type(conn) == "REAL":
            return "already REAL - nothing to do"

        rows = conn.execute(
            "SELECT sector_id, date, sector_name, performance, sector_return_pct FROM sectors ORDER BY sector_id"
        ).fetchall()
        converted, bad = [], []
        for sid, d, name, perf, pct in rows:
            try:
                converted.append((sid, d, name, perf, _as_number(pct)))
            except ValueError:
                bad.append((sid, d, name, pct))
        if bad:
            lines = "\n".join(f"  sector_id={b[0]} {b[1]} {b[2]}: {b[3]!r}" for b in bad[:20])
            raise SystemExit(f"[ABORT] {len(bad)} value(s) are not numbers; nothing was changed:\n{lines}")

        nulls = sum(1 for r in converted if r[4] is None)
        total = sum(r[4] for r in converted if r[4] is not None)
        summary = f"{len(rows)} rows, {nulls} NULL, sum {total:.6f}"
        if dry_run:
            return f"DRY RUN ok: would convert {summary}"

        conn.execute("PRAGMA foreign_keys = OFF")  # required for the rebuild; re-checked below
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DROP TABLE IF EXISTS sectors_new")
            conn.execute(NEW_TABLE_SQL)
            conn.executemany("INSERT INTO sectors_new VALUES (?,?,?,?,?)", converted)
            conn.execute("DROP TABLE sectors")
            conn.execute("ALTER TABLE sectors_new RENAME TO sectors")

            n, n_null, n_text, s = conn.execute(
                "SELECT COUNT(*), SUM(sector_return_pct IS NULL), "
                "SUM(typeof(sector_return_pct)='text'), TOTAL(sector_return_pct) FROM sectors").fetchone()
            ids_ok = [r[0] for r in conn.execute("SELECT sector_id FROM sectors ORDER BY sector_id")] \
                == [r[0] for r in rows]
            if not (n == len(rows) and (n_null or 0) == nulls and not n_text
                    and abs(s - total) < 1e-9 and ids_ok):
                raise RuntimeError(f"verification failed: rows={n} nulls={n_null} text={n_text} sum={s} ids_ok={ids_ok}")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("foreign_key_check reported violations")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return f"converted {summary}; verified"
    finally:
        conn.close()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry, skip_backup = "--dry-run" in argv, "--no-backup" in argv
    if not dry and not skip_backup:
        r = subprocess.run([sys.executable, str(PROJECT_ROOT / "ops" / "backup.py")], cwd=PROJECT_ROOT)
        if r.returncode != 0:
            print("[ABORT] backup failed; database not touched.")
            return r.returncode
    print("[OK]", convert(config.DB_PATH, dry_run=dry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
