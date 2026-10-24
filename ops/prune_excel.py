"""Prune old dated records from all historical-data worksheets.

The SQLite database is the permanent historical store. The Excel workbook is
kept lightweight by retaining the latest ``RETENTION_DAYS`` distinct dates in
all dated data sheets. Reference sheets (for example Metadata and Lists) are
never pruned.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import openpyxl
from openpyxl.utils.cell import range_boundaries

import config

RETENTION_DAYS = 15

# Explicit allowlist: never delete rows from sheets that are not historical data.
# The trailing space in "Events_page " matches the current workbook's sheet name.
PRUNABLE_SHEETS = (
    "DailyData",
    "Market_Vibe",
    "sectors",
    "Events_page ",
    "Learnings",
)


def _normalize_date(value: Any) -> date | None:
    """Convert supported Excel/Python date values to a comparable date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # Accept common ISO-style date strings, including datetime strings.
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
    return None


def get_header_map(ws) -> dict[str, int]:
    """Map trimmed, case-insensitive header names to 1-based column indexes."""
    result: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        value = ws.cell(row=1, column=col).value
        if value is not None:
            result[str(value).strip().casefold()] = col
    return result


def prune_sheet(ws, retention_limit: int = RETENTION_DAYS) -> int:
    """Keep the newest N distinct dates; for each date, retain every row.

    Rows with blank or unrecognizable dates are deliberately left untouched.
    Returns the number of deleted rows.
    """
    if retention_limit < 1:
        raise ValueError("retention_limit must be at least 1")

    headers = get_header_map(ws)
    date_col = headers.get("date")
    if date_col is None:
        print(f"[SKIP] Sheet '{ws.title}' has no date column; left unchanged.")
        return 0

    dated_rows: list[tuple[int, date]] = []
    for row_idx in range(2, ws.max_row + 1):
        row_date = _normalize_date(ws.cell(row=row_idx, column=date_col).value)
        if row_date is not None:
            dated_rows.append((row_idx, row_date))

    distinct_dates = sorted({row_date for _, row_date in dated_rows})
    if len(distinct_dates) <= retention_limit:
        print(
            f"[INFO] Sheet '{ws.title}' has {len(distinct_dates)} distinct dated "
            f"records (<= {retention_limit}); no pruning needed."
        )
        return 0

    keep_dates = set(distinct_dates[-retention_limit:])
    rows_to_delete = [
        row_idx for row_idx, row_date in dated_rows if row_date not in keep_dates
    ]
    if not rows_to_delete:
        return 0

    # Adjust Excel table ranges before deleting rows, because openpyxl does not
    # automatically resize table refs after Worksheet.delete_rows().
    old_table_ranges: dict[str, tuple[int, int, int, int]] = {}
    for table_name in list(ws.tables.keys()):
        table = ws.tables[table_name]
        old_table_ranges[table_name] = range_boundaries(table.ref)

    print(
        f"[INFO] Pruning {len(rows_to_delete)} old row(s) from '{ws.title}', "
        f"keeping {retention_limit} distinct dates."
    )
    for row_idx in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(row_idx, amount=1)

    deleted_rows = set(rows_to_delete)
    for table_name, (min_col, min_row, max_col, max_row) in old_table_ranges.items():
        table = ws.tables[table_name]
        deleted_inside_table = sum(
            1 for row_idx in deleted_rows if min_row < row_idx <= max_row
        )
        new_max_row = max(min_row, max_row - deleted_inside_table)
        col_start = openpyxl.utils.get_column_letter(min_col)
        col_end = openpyxl.utils.get_column_letter(max_col)
        new_ref = f"{col_start}{min_row}:{col_end}{new_max_row}"
        table.ref = new_ref
        if table.autoFilter is not None:
            table.autoFilter.ref = new_ref

    return len(rows_to_delete)


def prune_workbook(excel_path: Path, retention_limit: int = RETENTION_DAYS) -> dict[str, int]:
    """Prune every allowlisted data sheet and save once, preserving other sheets."""
    excel_path = Path(excel_path)
    if not excel_path.is_file():
        raise FileNotFoundError(f"Excel workbook not found: {excel_path}")

    print(f"[INFO] Loading workbook for pruning: {excel_path}")
    wb = openpyxl.load_workbook(excel_path)
    results: dict[str, int] = {}
    for sheet_name in PRUNABLE_SHEETS:
        if sheet_name not in wb.sheetnames:
            print(f"[WARNING] Expected data sheet '{sheet_name}' not found; skipped.")
            continue
        results[sheet_name] = prune_sheet(wb[sheet_name], retention_limit)

    total_deleted = sum(results.values())
    if total_deleted == 0:
        print("[INFO] No pruning required; workbook was not rewritten.")
        wb.close()
        return results

    # Create a timestamped safety copy of the original file before saving changes.
    backup_dir = config.BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{excel_path.stem}_backup_{timestamp}{excel_path.suffix}"
    shutil.copy2(excel_path, backup_path)

    wb.save(excel_path)
    wb.close()
    print(f"[SUCCESS] Pruned workbook. Safety backup: {backup_path}")
    for sheet_name, count in results.items():
        print(f"  {sheet_name!r}: {count} row(s) removed")
    return results


def main() -> None:
    prune_workbook(config.EXCEL_PATH, RETENTION_DAYS)


if __name__ == "__main__":
    main()
