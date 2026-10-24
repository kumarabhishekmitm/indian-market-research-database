"""
update_daily_data.py
---------------------
CLI entry point for daily market data execution with full error tracing.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Enforce project root on sys.path so config and core modules load from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import config
    from daily_update import run_update, get_market_today
    from data_source import YFinanceDataSource
except Exception as e:
    print(f"[CRITICAL ERROR] Failed to import pipeline dependencies: {e}")
    sys.exit(1)


def parse_args(argv):
    debug = "--debug" in argv
    argv = [a for a in argv if a != "--debug"]
    date_arg = argv[0] if argv else None
    return date_arg, debug


def _write_log(log_lines):
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== Run started {dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write("\n".join(log_lines) + "\n")
    except OSError:
        pass


def main(argv) -> int:
    date_arg, debug = parse_args(argv)
    explicit_date = None

    if date_arg:
        try:
            explicit_date = dt.date.fromisoformat(date_arg)
        except ValueError:
            print(f"[ERROR] Invalid date format '{date_arg}'. Expected YYYY-MM-DD.")
            return 1

    log_lines = []

    def sink(line: str):
        print(line)
        log_lines.append(line)

    try:
        result = run_update(
            data_source=YFinanceDataSource(),
            today=get_market_today(),
            explicit_date=explicit_date,
            sink=sink,
            debug=debug,
        )
    except Exception as e:
        import traceback
        sink(f"[CRITICAL ERROR] Unhandled exception during run_update: {e}")
        log_lines.extend(traceback.format_exc().splitlines())  # crashes must reach run_log.txt
        _write_log(log_lines)
        if debug:
            traceback.print_exc()
        return 1

    _write_log(log_lines)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))