"""
ops/backup.py
-------------
1. Backs up market.db (using SQLite's own backup API, so the copy is
   consistent even if the DB is in use) to data/backups/market_<ts>.db
   and verifies the copy with PRAGMA integrity_check.
2. Backs up the Excel workbook to data/backups/<stem>_backup_<ts>.xlsx.
3. Keeps only the newest config.KEEP_BACKUPS of each kind. "Newest" is taken
   from the timestamp in the FILE NAME (file mtimes are changed by copies).

Raises (non-zero exit when run as a script) if the database is missing or
the backup fails verification, so the pipeline stops BEFORE touching data.
"""

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

DB_BACKUP_PATTERN = "market_*.db"


def excel_backup_pattern(excel_path: Path) -> str:
    return f"{excel_path.stem}_backup_*.xlsx"


def prune_backups(backup_dir: Path, pattern: str, keep: int) -> int:
    """Delete the oldest files matching pattern, keeping the newest `keep`."""
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.name, reverse=True)
    removed = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError as e:
            print(f"WARNING: could not delete {old.name}: {e}")
    return removed


def backup_database(db_path: Path, backup_dir: Path, stamp: str) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found at {db_path}")
    dest = backup_dir / f"market_{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(dest)
    try:
        result = check.execute("PRAGMA integrity_check;").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed integrity_check: {result}")
    return dest


def main(db_path=None, excel_path=None, backup_dir=None, keep=None):
    db_path = Path(db_path or config.DB_PATH)
    excel_path = Path(excel_path or config.EXCEL_PATH)
    backup_dir = Path(backup_dir or config.BACKUP_DIR)
    keep = keep or config.KEEP_BACKUPS
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    db_backup = backup_database(db_path, backup_dir, stamp)
    print(f"Database backup created: {db_backup} ({db_backup.stat().st_size} bytes)")

    if excel_path.exists():
        xl = backup_dir / f"{excel_path.stem}_backup_{stamp}{excel_path.suffix}"
        shutil.copy2(excel_path, xl)
        print(f"Workbook backup created: {xl}")
    else:
        print(f"WARNING: workbook not found at {excel_path}; no workbook backup made.")

    removed_db = prune_backups(backup_dir, DB_BACKUP_PATTERN, keep)
    removed_xl = prune_backups(backup_dir, excel_backup_pattern(excel_path), keep)
    print(f"Pruned {removed_db} old .db and {removed_xl} old workbook backup(s); keeping newest {keep} of each.")
    return db_backup


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] Backup failed: {e}")
        sys.exit(1)
