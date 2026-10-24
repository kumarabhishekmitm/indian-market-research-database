"""
Step 19: Data quality report.

Summarizes everything in data_quality_issues: counts per sheet, counts
per issue type, and the full detail list. Prints to screen AND saves a
timestamped copy to reports/, so you have a historical record of data
quality over time (not just "right now").

Read-only on the database — only writes a new file under reports/.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "market.db"
REPORTS_DIR = BASE_DIR / "reports"


def build_report_text(conn):
    lines = []
    lines.append("=" * 70)
    lines.append(f"DATA QUALITY REPORT — generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    total = conn.execute("SELECT COUNT(*) FROM data_quality_issues;").fetchone()[0]
    lines.append(f"\nTotal issues logged: {total}")

    if total == 0:
        lines.append("\nNo data quality issues found. Every row loaded cleanly.")
        return "\n".join(lines)

    lines.append("\n--- Issues by sheet ---")
    by_sheet = conn.execute("""
        SELECT source_sheet, COUNT(*) FROM data_quality_issues
        GROUP BY source_sheet ORDER BY COUNT(*) DESC;
    """).fetchall()
    for sheet, count in by_sheet:
        lines.append(f"  {sheet}: {count}")

    lines.append("\n--- Issues by type (grouped by description pattern) ---")
    # Group by the description text itself, since our descriptions are
    # consistent short phrases (e.g. "Completely blank row"), not
    # free-form text with unique details every time.
    by_type = conn.execute("""
        SELECT issue_description, COUNT(*) FROM data_quality_issues
        GROUP BY issue_description ORDER BY COUNT(*) DESC;
    """).fetchall()
    for desc, count in by_type:
        lines.append(f"  {desc}: {count}")

    lines.append("\n--- Full detail (sheet, row number, description) ---")
    details = conn.execute("""
        SELECT source_sheet, source_row_number, issue_description, logged_at
        FROM data_quality_issues
        ORDER BY source_sheet, source_row_number;
    """).fetchall()
    for sheet, row_num, desc, logged_at in details:
        lines.append(f"  [{sheet}] row {row_num}: {desc} (logged {logged_at})")

    return "\n".join(lines)


def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    report_text = build_report_text(conn)
    conn.close()

    print(report_text)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"data_quality_report_{timestamp}.txt"
    report_path.write_text(report_text, encoding="utf-8")

    print(f"\n\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()