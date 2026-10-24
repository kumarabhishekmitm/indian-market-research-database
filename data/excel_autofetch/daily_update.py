"""
daily_update.py
----------------
Core orchestration engine. Manages state machine, evaluates holidays,
enforces multi-day catch-up, and provides granular field-level reporting.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

import config
import excel_ops
import holiday_state
from data_source import DayBar, FetchResult, NetworkError, MalformedResponseError, DataSourceError, validate_ohlc


class Status(str, Enum):
    SUCCESS_CATCHUP_COMPLETE = "SUCCESS_CATCHUP_COMPLETE"
    NO_ACTION_ALREADY_COMPLETE = "NO_ACTION_ALREADY_COMPLETE"
    NO_ACTION_WEEKEND = "NO_ACTION_WEEKEND"
    NO_ACTION_DATA_NOT_YET_AVAILABLE = "NO_ACTION_DATA_NOT_YET_AVAILABLE"
    NO_ACTION_FUTURE_DATE = "NO_ACTION_FUTURE_DATE"
    NO_ACTION_NOTHING_TO_DO = "NO_ACTION_NOTHING_TO_DO"
    ERROR_WORKBOOK_PROBLEM = "ERROR_WORKBOOK_PROBLEM"
    ERROR_NETWORK = "ERROR_NETWORK"
    ERROR_MALFORMED = "ERROR_MALFORMED"
    ERROR_INVALID_DATA = "ERROR_INVALID_DATA"
    ERROR_DUPLICATE_DATES = "ERROR_DUPLICATE_DATES"
    ERROR_UNEXPECTED = "ERROR_UNEXPECTED"


@dataclass
class Result:
    status: Status
    logs: List[str] = field(default_factory=list)
    row_reports: List["excel_ops.RowWriteReport"] = field(default_factory=list)
    backup_path: Optional[Path] = None

    @property
    def ok(self) -> bool:
        return not self.status.value.startswith("ERROR")


class Logger:
    def __init__(self, sink: Optional[Callable[[str], None]] = None):
        self.lines: List[str] = []
        self._sink = sink

    def _emit(self, tag: str, msg: str):
        line = f"[{tag}] {msg}"
        self.lines.append(line)
        if self._sink:
            self._sink(line)

    def info(self, msg: str):
        self._emit("INFO", msg)

    def error(self, msg: str):
        self._emit("ERROR", msg)

    def success(self, msg: str):
        self._emit("SUCCESS", msg)


def get_market_today(tz_name: str = config.MARKET_TIMEZONE) -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return dt.date.today()


def session_still_open(target_date: dt.date, today: dt.date, now: Optional[dt.datetime] = None) -> bool:
    """True if `target_date` is today and the market has not closed yet.

    Yahoo returns an in-progress daily bar during the session. Because cells
    are never overwritten once filled, accepting that bar would lock a
    partial price in permanently - so today's date is refused until after
    config.MARKET_CLOSE_TIME (IST). `now` can be injected for tests.
    """
    if target_date != today:
        return False
    tz = ZoneInfo(config.MARKET_TIMEZONE)
    now = now.astimezone(tz) if now and now.tzinfo else (now or dt.datetime.now(tz))
    return (now.hour, now.minute) < config.MARKET_CLOSE_TIME


def next_weekday(d: dt.date | dt.datetime | str) -> dt.date:
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    elif isinstance(d, dt.datetime):
        d = d.date()

    d = d + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d = d + dt.timedelta(days=1)
    return d


def classify_ticker(data_source, ticker_key: str, symbol: str, target_date: dt.date, log: Logger) -> tuple:
    try:
        result: FetchResult = data_source.fetch_ticker(symbol, target_date)
    except NetworkError as e:
        return None, None, f"network error: {e}", None
    except MalformedResponseError as e:
        return None, None, f"malformed response: {e}", None
    except DataSourceError as e:
        return None, None, f"data source error: {e}", None

    if result.bar_on_target_date is None:
        return None, result.prev_close, None, result.has_bars_after_target_date

    problem = validate_ohlc(result.bar_on_target_date)
    if problem:
        return None, result.prev_close, f"failed OHLC validation: {problem}", result.has_bars_after_target_date

    return result.bar_on_target_date, result.prev_close, None, result.has_bars_after_target_date


def print_detailed_report(report: excel_ops.RowWriteReport, log: Logger):
    """Print granular column-level fill and skip status to console/sink."""
    log.info(f"--- Granular Report for Date: {report.target_date} (Row {report.row_index}) ---")
    
    if report.filled:
        log.success(f"  Successfully Auto-Filled ({len(report.filled)} columns):")
        for col in report.filled:
            log.lines.append(f"    - {col}")
            if log._sink:
                log._sink(f"    - {col}")

    if report.skipped_no_data:
        log.info(f"  Skipped (No Data Available from API) ({len(report.skipped_no_data)} columns):")
        for col in report.skipped_no_data:
            log.lines.append(f"    - {col} [Reason: API returned no bar/value]")
            if log._sink:
                log._sink(f"    - {col} [Reason: API returned no bar/value]")

    if report.skipped_invalid:
        log.error(f"  Skipped Due to Validation Errors ({len(report.skipped_invalid)} columns):")
        for item in report.skipped_invalid:
            msg = f"    - {item['column']}: {item['reason']}"
            log.lines.append(msg)
            if log._sink:
                log._sink(msg)

    if report.still_manual:
        log.info(f"  Highlighted Yellow for Manual Entry ({len(report.still_manual)} columns):")
        for col in report.still_manual:
            log.lines.append(f"    - {col} [Pending your manual journal/notes]")
            if log._sink:
                log._sink(f"    - {col} [Pending your manual journal/notes]")
    log.info("-" * 65)


def run_update(
    data_source,
    today: Optional[dt.date] = None,
    explicit_date: Optional[dt.date] = None,
    excel_path: Optional[Path] = None,
    sink: Optional[Callable[[str], None]] = None,
    debug: bool = False,
    now: Optional[dt.datetime] = None,
) -> Result:
    log = Logger(sink)
    excel_path = excel_path or config.EXCEL_PATH
    today = today if today is not None else get_market_today()

    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    elif isinstance(today, dt.datetime):
        today = today.date()

    try:
        excel_ops.check_workbook_exists(excel_path)
    except excel_ops.WorkbookProblem as e:
        log.error(str(e))
        return Result(Status.ERROR_WORKBOOK_PROBLEM, log.lines)

    log.info(f"Workbook found: {excel_path}")
    temp_path = None

    try:
        temp_path = excel_ops.make_working_copy(excel_path)
        wb = excel_ops.open_workbook(temp_path)
        ws, table = excel_ops.get_sheet_and_table(wb)
        headers = excel_ops.get_header_map(ws)
        excel_ops.check_required_headers(headers)

        dupes = excel_ops.find_duplicate_dates(ws, headers)
        if dupes:
            log.error(f"Duplicate dates exist in sheet: {dupes}")
            return Result(Status.ERROR_DUPLICATE_DATES, log.lines)

        confirmed_holidays = holiday_state.load(config.CONFIRMED_HOLIDAYS_FILE)

        # Determine target dates to process (Multi-day catch-up support)
        target_dates = []
        not_ready = False

        if explicit_date is not None:
            target_date = explicit_date
            if target_date > today:
                log.error(f"{target_date} is in the future. Refusing update.")
                return Result(Status.NO_ACTION_FUTURE_DATE, log.lines)
            if target_date.weekday() >= 5:
                log.info(f"{target_date} is a weekend.")
                return Result(Status.NO_ACTION_WEEKEND, log.lines)
            if session_still_open(target_date, today, now):
                log.info(f"{target_date}: market session not finished yet (before "
                         f"{config.MARKET_CLOSE_TIME[0]:02d}:{config.MARKET_CLOSE_TIME[1]:02d} IST). Run again after close.")
                return Result(Status.NO_ACTION_DATA_NOT_YET_AVAILABLE, log.lines)
            target_dates.append(target_date)
        else:
            last_dated = excel_ops.get_last_dated_row(ws, headers)
            if last_dated is None:
                log.error("Workbook contains no dated rows.")
                return Result(Status.ERROR_WORKBOOK_PROBLEM, log.lines)

            last_row_idx, last_date = last_dated
            if isinstance(last_date, str):
                last_date = dt.date.fromisoformat(last_date)
            elif isinstance(last_date, dt.datetime):
                last_date = last_date.date()

            # Check if last row is incomplete
            close_col = headers["nifty_close"]
            last_row_incomplete = ws.cell(row=last_row_idx, column=close_col).value in (None, "")

            candidate = last_date if last_row_incomplete else next_weekday(last_date)

            # Build queue of missing trading days up to today
            while candidate <= today:
                if candidate.weekday() >= 5:
                    candidate = next_weekday(candidate)
                    continue
                if candidate in confirmed_holidays:
                    candidate = next_weekday(candidate)
                    continue
                if session_still_open(candidate, today, now):
                    log.info(f"{candidate}: market session not finished yet - not fetching today's partial bar.")
                    candidate = next_weekday(candidate)
                    not_ready = True
                    continue
                target_dates.append(candidate)
                candidate = next_weekday(candidate)

            if not target_dates:
                if not_ready:
                    return Result(Status.NO_ACTION_DATA_NOT_YET_AVAILABLE, log.lines)
                log.info("Workbook is fully up to date with market calendar.")
                return Result(Status.NO_ACTION_ALREADY_COMPLETE, log.lines)

        log.info(f"Target dates queued for catch-up processing: {target_dates}")

        all_reports = []
        processed_any = False

        for target_date in target_dates:
            log.info(f"Processing target date: {target_date}")

            primary_key = config.PRIMARY_TICKER
            primary_symbol = config.TICKERS[primary_key]
            bar, prev_close, reason, has_after = classify_ticker(data_source, primary_key, primary_symbol, target_date, log)

            if bar is None and reason and "network" in reason:
                log.error(f"Yahoo Finance network error on {target_date}: {reason}")
                return Result(Status.ERROR_NETWORK, log.lines)

            if bar is None and reason:
                log.error(f"Primary ticker {primary_key} validation failure on {target_date}: {reason}")
                return Result(Status.ERROR_INVALID_DATA, log.lines)

            if bar is None:
                if has_after:
                    log.info(f"Market data unavailable for {target_date} (skipping for now, not writing to holiday state).")
                    continue  # Skip this date for this run without locking it as a holiday
                else:
                    log.info(f"No market data available yet for {target_date} (live session ongoing or future).")
                    not_ready = True
                    break  # Stop catch-up queue if today's data isn't ready yet

            validated_bars = {primary_key: bar}
            prev_closes = {primary_key: prev_close}
            unavailable = {}

            for key, symbol in config.TICKERS.items():
                if key == primary_key:
                    continue
                s_bar, s_prev, s_reason, _ = classify_ticker(data_source, key, symbol, target_date, log)
                prev_closes[key] = s_prev
                if s_bar is not None:
                    validated_bars[key] = s_bar
                elif s_reason:
                    unavailable[key] = s_reason

            existing_row = excel_ops.find_row_for_date(ws, headers, target_date)
            if existing_row:
                row_idx = existing_row
                is_new_row = False
            else:
                last_dated_current = excel_ops.get_last_dated_row(ws, headers)
                row_idx = (last_dated_current[0] + 1) if last_dated_current else 2
                is_new_row = True
                excel_ops.ensure_row_ready(ws, table, row_idx, headers)
                excel_ops.apply_new_row_formatting(ws, table, row_idx)

            report = excel_ops.write_objective_fields(
                ws, headers, row_idx, target_date, validated_bars, prev_closes, unavailable
            )
            report.is_new_row = is_new_row
            all_reports.append(report)
            print_detailed_report(report, log)
            processed_any = True

        if not processed_any:
            log.info("No new rows added or updated during this run.")
            return Result(Status.NO_ACTION_DATA_NOT_YET_AVAILABLE if not_ready else Status.NO_ACTION_NOTHING_TO_DO, log.lines)

        wb.save(temp_path)
        last_processed_row = all_reports[-1].row_index if all_reports else 2
        excel_ops.validate_saved_workbook(temp_path, expected_min_row=last_processed_row)
        backup_path = excel_ops.atomic_publish(temp_path, excel_path, config.BACKUP_DIR)
        temp_path = None
        excel_ops.cleanup_old_backups(excel_path, config.BACKUP_DIR)

        log.success("Successfully completed catch-up update cycle.")
        return Result(Status.SUCCESS_CATCHUP_COMPLETE, log.lines, row_reports=all_reports, backup_path=backup_path)

    except excel_ops.WorkbookProblem as e:
        log.error(f"Workbook problem: {e}")
        return Result(Status.ERROR_WORKBOOK_PROBLEM, log.lines)
    except Exception as e:
        log.error(f"Execution halted: {e}")
        if debug:
            raise
        return Result(Status.ERROR_UNEXPECTED, log.lines)
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass