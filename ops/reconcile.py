"""
ops/reconcile.py
----------------
SAFETY GATE that runs before the workbook is pruned.

prune_excel.py deletes old rows from Excel on the assumption that SQLite
already holds them. This script checks that assumption: for every workbook
row that pruning WOULD delete, every non-blank Excel value must already be
present, and equal, in SQLite.

Exit code 0 = safe to prune, 1 = pruning would lose data (details printed).
"""

import sqlite3
import sys
from pathlib import Path

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from ingest.migrate_from_excel import (
    DAILY_COLUMNS, MARKET_VIBE_COLUMNS, _norm_header, clean_value,
    get_sheet_names, to_iso_date,
)
from ops.prune_excel import RETENTION_DAYS, _normalize_date

# logical sheet key -> (table, key column)
SHEETS = {
    "daily_data": ("daily_data", "date"),
    "market_vibe": ("market_vibe", "date"),
    "sectors": ("sectors", "sector_id"),
    "events": ("events", "event_id"),
    "learnings": ("learnings", "learning_id"),
}


def _same(excel_val, db_val):
    if excel_val is None:
        return True  # nothing in Excel that could be lost
    if db_val is None:
        return False
    try:
        return abs(float(excel_val) - float(db_val)) < 1e-6
    except (TypeError, ValueError):
        return str(excel_val).strip() == str(db_val).strip()


def _sheet_records(ws, key):
    """Yield (row_number, excel_date, record) with record = {column: value}."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return
    if key == "market_vibe":
        names = ["date"] + MARKET_VIBE_COLUMNS
    else:
        names = [_norm_header(h) for h in rows[0] if h is not None]
    for n, row in enumerate(rows[1:], start=2):
        rec = dict(zip(names, row))
        raw_date = rec.get("date")
        if raw_date is None:
            continue  # prune leaves undated rows alone
        d = _normalize_date(raw_date)
        if d is None:
            continue
        rec = {k: clean_value(v) for k, v in rec.items()}
        rec["date"] = to_iso_date(raw_date) or d.isoformat()
        yield n, d, rec


def find_problems(db_path=None, wb_path=None, retention=RETENTION_DAYS):
    db_path = Path(db_path or config.DB_PATH)
    wb_path = Path(wb_path or config.EXCEL_PATH)
    wb = load_workbook(wb_path, read_only=True, data_only=True)
    sheets = get_sheet_names(wb)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    problems = []
    try:
        for key, (table, key_col) in SHEETS.items():
            if sheets[key] not in wb.sheetnames:
                continue
            records = list(_sheet_records(wb[sheets[key]], key))
            distinct = sorted({d for _, d, _ in records})
            if len(distinct) <= retention:
                continue
            keep = set(distinct[-retention:])
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for n, d, rec in records:
                if d in keep:
                    continue  # not going to be pruned
                key_val = rec[key_col]
                row = conn.execute(f"SELECT * FROM {table} WHERE {key_col} = ?", (key_val,)).fetchone()
                label = f"{sheets[key]!r} row {n} ({key_col}={key_val})"
                if row is None:
                    problems.append(f"{label}: not in database")
                    continue
                dbrec = dict(zip(cols, row))
                for col, val in rec.items():
                    if col in dbrec and not _same(val, dbrec[col]):
                        problems.append(f"{label}: {col} Excel={val!r} DB={dbrec[col]!r}")
    finally:
        conn.close()
        wb.close()
    return problems


def main(db_path=None, wb_path=None):
    problems = find_problems(db_path, wb_path)
    if not problems:
        print("[OK] Every workbook row that would be pruned is fully present in the database.")
        return 0
    print(f"[FAIL] Pruning would lose data: {len(problems)} mismatch(es). Nothing was pruned.")
    for p in problems[:50]:
        print("  -", p)
    if len(problems) > 50:
        print(f"  ... and {len(problems) - 50} more")
    print("Fix the database (or the cell in Excel) and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
