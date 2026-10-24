"""
ops/clear_stale_issues.py
-------------------------
Removes stale rows from data_quality_issues -- rows logged by older versions
of the migration script that the current script no longer produces.

Safe by design:
  * Preview only unless --apply is passed.
  * Requires --before so you must choose an explicit cutoff; only rows with
    logged_at earlier than that date are touched.
  * With --apply: makes a database backup, archives the rows to a CSV in
    reports/, then deletes them.

Usage:
    python ops/clear_stale_issues.py --before 2026-09-25            (preview)
    python ops/clear_stale_issues.py --before 2026-09-25 --apply    (do it)
"""

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from ops import backup

REPORTS_DIR = PROJECT_ROOT / "reports"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", required=True, help="Only remove issues logged before this date (YYYY-MM-DD).")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default is preview only).")
    args = parser.parse_args()
    try:
        date.fromisoformat(args.before)
    except ValueError:
        parser.error("--before must be a date in YYYY-MM-DD format.")
    return args


def main():
    args = parse_args()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT issue_id, source_sheet, source_row_number, issue_description, raw_row_data, logged_at "
            "FROM data_quality_issues WHERE logged_at < ? ORDER BY issue_id;",
            (args.before,),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM data_quality_issues;").fetchone()[0]

        print(f"{len(rows)} of {total} issue(s) were logged before {args.before}.")
        for sheet, n in conn.execute(
            "SELECT source_sheet, COUNT(*) FROM data_quality_issues WHERE logged_at < ? GROUP BY 1 ORDER BY 2 DESC;",
            (args.before,),
        ):
            print(f"  {sheet.strip()}: {n}")

        if not rows:
            return
        if not args.apply:
            print("\nPreview only. Re-run with --apply to archive and delete these rows.")
            return

        backup.main()

        REPORTS_DIR.mkdir(exist_ok=True)
        archive = REPORTS_DIR / f"data_quality_issues_archive_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(archive, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["issue_id", "source_sheet", "source_row_number", "issue_description", "raw_row_data", "logged_at"])
            writer.writerows(rows)
        print(f"Archived {len(rows)} row(s) to {archive}")

        conn.execute("DELETE FROM data_quality_issues WHERE logged_at < ?;", (args.before,))
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM data_quality_issues;").fetchone()[0]
        print(f"Deleted {len(rows)} row(s). {remaining} issue(s) remain.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
