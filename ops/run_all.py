"""
ops/run_all.py
--------------
Daily pipeline. Every step is a hard gate: if a script is missing or fails,
the pipeline stops and nothing after it runs.

  0. Tests         - run FIRST, so a broken code change never touches your data
  1. Backup        - verified DB backup + workbook backup
  2. Import        - Excel -> SQLite (fills blanks, never overwrites)
  3. Validate      - integrity, foreign keys, orphans, quality issues
  3b. Data checks  - holiday-aware completeness, freshness, OHLC logic, ranges
  4. Reconcile     - proves Excel rows about to be pruned are fully in SQLite
  5. Prune         - trim the workbook to its retention window
  6. Format        - re-apply drop-downs and formulas

(Analysis, dashboard and CSV export are separate commands - see README.)
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config


def print_step(title: str):
    print("\n" + "=" * 70)
    print(f"PIPELINE STEP: {title}")
    print("=" * 70)


def run(cmd, description: str):
    print_step(description)
    result = subprocess.run(cmd, check=False, cwd=config.PROJECT_ROOT)
    if result.returncode != 0:
        print(f"\n[ERROR] Pipeline halted at step: {description}")
        sys.exit(result.returncode)


def run_script(relative_path: str, description: str):
    script = config.PROJECT_ROOT / relative_path
    if not script.exists():
        # A missing gate must stop the pipeline, never be skipped silently.
        print(f"\n[ERROR] Required script not found: {script}")
        print(f"[ERROR] Pipeline halted at step: {description}")
        sys.exit(2)
    run([sys.executable, str(script)], description)


def main():
    print("#" * 70)
    print(" STARTING DAILY MARKET DATABASE PIPELINE")
    print("#" * 70)

    run([sys.executable, "-m", "pytest", "-q"], "0. Test suite (pre-flight)")
    run_script("ops/backup.py", "1. Backup database and workbook")
    run_script("ops/validate_excel.py", "1b. Validate workbook BEFORE import")
    run_script("ingest/migrate_from_excel.py", "2. Import Excel data to SQLite")
    run_script("ops/validate_db.py", "3. Validate database")
    run_script("ops/data_checks.py", "3b. Professional data checks (calendar-aware)")
    run_script("ops/reconcile.py", "4. Reconcile workbook against database")
    run_script("ops/prune_excel.py", "5. Prune workbook")
    run_script("ops/apply_excel_formatting.py", "6. Re-apply formatting and validation")

    print("\n[SUCCESS] Pipeline completed.")


if __name__ == "__main__":
    main()
