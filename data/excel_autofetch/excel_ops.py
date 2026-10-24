"""
excel_ops.py
------------
Transactional Excel workbook manipulation using atomic file writes.
Auto-reconstructs structural Table objects and checks data integrity post-write.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
from copy import copy as _copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.table import Table, TableStyleInfo

import config

YELLOW = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
NO_FILL = PatternFill(fill_type=None)


class WorkbookProblem(Exception):
    """Raised on critical Excel structural or file system violations."""


@dataclass
class RowWriteReport:
    row_index: int
    target_date: dt.date
    is_new_row: bool
    filled: List[str] = field(default_factory=list)
    skipped_no_data: List[str] = field(default_factory=list)
    skipped_invalid: List[Dict[str, str]] = field(default_factory=list)
    still_manual: List[str] = field(default_factory=list)


def check_workbook_exists(excel_path: Path) -> None:
    if not excel_path.exists():
        raise WorkbookProblem(f"Workbook not found at: {excel_path}")
    if not excel_path.is_file():
        raise WorkbookProblem(f"Path exists but is not a file: {excel_path}")


def open_workbook(excel_path: Path):
    try:
        return load_workbook(excel_path)
    except Exception as e:
        raise WorkbookProblem(f"Unable to open workbook '{excel_path}': {e}") from e


def get_sheet_and_table(wb):
    if config.SHEET_NAME not in wb.sheetnames:
        raise WorkbookProblem(f"Sheet '{config.SHEET_NAME}' not found in workbook.")

    ws = wb[config.SHEET_NAME]

    # Dynamic Table Reconstruction Guardrail
    if config.TABLE_NAME not in ws.tables:
        max_col = ws.max_column
        max_row = max(ws.max_row, 2)
        col_letter = get_column_letter(max_col)

        table_ref = f"A1:{col_letter}{max_row}"
        tab = Table(displayName=config.TABLE_NAME, ref=table_ref)
        tab.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(tab)

    return ws, ws.tables[config.TABLE_NAME]


def get_header_map(ws, header_row: int = 1) -> Dict[str, int]:
    headers = {}
    for cell in ws[header_row]:
        if cell.value:
            headers[str(cell.value).strip()] = cell.column
    return headers


def check_required_headers(headers: Dict[str, int]) -> None:
    missing = [h for h in config.REQUIRED_HEADERS if h not in headers]
    if missing:
        raise WorkbookProblem(f"Workbook headers missing required columns: {missing}")


def all_dated_rows(ws, headers) -> List[tuple]:
    date_col = headers["date"]
    out = []
    for row in range(2, ws.max_row + 1):
        v = ws.cell(row=row, column=date_col).value
        if v is None:
            continue
        d = v.date() if isinstance(v, dt.datetime) else v
        if isinstance(d, str):
            try:
                d = dt.date.fromisoformat(d)
            except ValueError:
                continue
        out.append((row, d))
    return out


def find_row_for_date(ws, headers, target_date: dt.date) -> Optional[int]:
    for row, d in all_dated_rows(ws, headers):
        if d == target_date:
            return row
    return None


def find_duplicate_dates(ws, headers) -> Dict[dt.date, List[int]]:
    seen: Dict[dt.date, List[int]] = {}
    for row, d in all_dated_rows(ws, headers):
        seen.setdefault(d, []).append(row)
    return {d: rows for d, rows in seen.items() if len(rows) > 1}


def get_last_dated_row(ws, headers) -> Optional[tuple]:
    rows = all_dated_rows(ws, headers)
    if not rows:
        return None
    return max(rows, key=lambda pair: pair[1])


def ensure_row_ready(ws, table, row_idx: int, headers: Dict[str, int]) -> None:
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    if row_idx <= max_row:
        return
    if row_idx != max_row + 1:
        raise WorkbookProblem(f"Gap detected when expanding table to row {row_idx}.")

    new_ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{row_idx}"
    table.ref = new_ref
    if table.autoFilter is not None:
        table.autoFilter.ref = new_ref


def apply_new_row_formatting(ws, table, row_idx: int) -> None:
    min_col, _, max_col, _ = range_boundaries(table.ref)
    template_row = row_idx - 1
    if template_row < 1:
        return
    for col in range(min_col, max_col + 1):
        src = ws.cell(row=template_row, column=col)
        dst = ws.cell(row=row_idx, column=col)
        dst.number_format = src.number_format
        dst.font = _copy(src.font)


def write_objective_fields(
    ws, headers: Dict[str, int], row_idx: int, target_date: dt.date,
    validated_bars: Dict[str, "data_source.DayBar"],
    prev_closes: Dict[str, Optional[float]],
    unavailable: Dict[str, str],
) -> RowWriteReport:
    report = RowWriteReport(row_index=row_idx, target_date=target_date, is_new_row=False)

    date_cell = ws.cell(row=row_idx, column=headers["date"])
    if date_cell.value is None:
        # Midnight, not the wall-clock time of the run: a trading date has no
        # time-of-day, and stray times break exact-match lookups/joins on date.
        date_cell.value = dt.datetime.combine(target_date, dt.time())
        date_cell.number_format = "yyyy-mm-dd"

    def cell_is_blank(header_name: str) -> bool:
        col = headers[header_name]
        v = ws.cell(row=row_idx, column=col).value
        return v is None or v == ""

    def set_value(header_name: str, value):
        col = headers[header_name]
        ws.cell(row=row_idx, column=col).value = value

    for header_name, (ticker_key, field_name) in config.AUTO_FIELD_MAP.items():
        if not cell_is_blank(header_name):
            continue
        bar = validated_bars.get(ticker_key)
        if bar is None:
            report.skipped_no_data.append(header_name)
            continue
        value = getattr(bar, field_name)
        set_value(header_name, round(float(value), 3))
        report.filled.append(header_name)

    nifty_bar = validated_bars.get("nifty")
    nifty_prev = prev_closes.get("nifty")
    vix_bar = validated_bars.get("vix")
    vix_prev = prev_closes.get("vix")

    def set_derived(header_name: str, value):
        if not cell_is_blank(header_name):
            return
        if value is None:
            report.skipped_no_data.append(header_name)
            return
        set_value(header_name, round(value, 2))
        report.filled.append(header_name)

    if nifty_bar and nifty_prev:
        set_derived("nifty_change_pts", nifty_bar.close - nifty_prev)
        set_derived("nifty_change_pct", ((nifty_bar.close - nifty_prev) / nifty_prev) * 100)
        set_derived("nifty_gap_pts", nifty_bar.open - nifty_prev)

    if vix_bar and vix_prev:
        set_derived("vix_change_pct", ((vix_bar.close - vix_prev) / vix_prev) * 100)

    for header_name, formula_template in config.FORMULA_COLUMNS.items():
        col = headers.get(header_name)
        if col:
            cell = ws.cell(row=row_idx, column=col)
            if cell.value in (None, ""):
                cell.value = formula_template.format(table=config.TABLE_NAME)

    for header_name in config.MANUAL_COLUMNS:
        col = headers[header_name]
        cell = ws.cell(row=row_idx, column=col)
        if cell.value in (None, ""):
            cell.fill = YELLOW
            report.still_manual.append(header_name)
        else:
            cell.fill = NO_FILL

    return report


def validate_saved_workbook(temp_path: Path, expected_min_row: int) -> None:
    try:
        wb = load_workbook(temp_path)
    except Exception as e:
        raise WorkbookProblem(f"Post-save load failure: {e}")

    ws = wb[config.SHEET_NAME]
    table = ws.tables[config.TABLE_NAME]
    _, _, _, max_row = range_boundaries(table.ref)

    if max_row < expected_min_row:
        raise WorkbookProblem(f"Table validation failed: row limit {max_row} < {expected_min_row}")


def make_working_copy(excel_path: Path) -> Path:
    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", prefix=excel_path.stem + "_work_", dir=str(excel_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    shutil.copy2(excel_path, tmp_path)
    return tmp_path


def atomic_publish(temp_path: Path, excel_path: Path, backup_dir: Path) -> Path:
    backup_path = backup_dir / f"{excel_path.stem}_backup_{dt.datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
    shutil.copy2(excel_path, backup_path)
    os.replace(temp_path, excel_path)
    return backup_path


def cleanup_old_backups(excel_path: Path, backup_dir: Path, keep: int = config.KEEP_BACKUPS) -> int:
    pattern = excel_path.stem + "_backup_*.xlsx"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.name, reverse=True)  # name carries the timestamp; mtime is altered by copy2
    removed = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed