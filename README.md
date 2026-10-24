# Indian Market Research Database

A personal pipeline that moves a hand-maintained Excel research workbook into a SQLite database, with safeguards and professional-style data checks at every step. It tracks Indian equity-market conditions over time: Nifty and India VIX, FII/DII activity, derivatives indicators, macro inputs (Brent, USD/INR, US 10-year yield), sector performance, events, and a personal forecast journal.

> **Important:** This is a personal research and journaling tool, not a trading system or investment advice. Third-party market data can be delayed, revised or incomplete. Verify anything important against the original source.

## Contents

- [How the data flows](#how-the-data-flows)
- [Quick start (Windows)](#quick-start-windows)
- [The daily pipeline, step by step](#the-daily-pipeline-step-by-step)
- [The checks](#the-checks)
- [Holiday calendar](#holiday-calendar)
- [Project structure](#project-structure)
- [Database tables](#database-tables)
- [Useful commands](#useful-commands)
- [Safeguards and recovery](#safeguards-and-recovery)
- [Troubleshooting](#troubleshooting)
- [Design rules to know about](#design-rules-to-know-about)
- [Yearly and one-time tasks](#yearly-and-one-time-tasks)

## How the data flows

```text
Market sources (Yahoo Finance) + your manual journal entries
                    |
                    v
        Excel workbook (Market_Database.xlsx)      <- keeps only the latest 15 trading days
                    |
   Tests -> Backup -> Excel pre-check
                    |
                    v
        Import into SQLite (market.db)             <- permanent history
                    |
   Database validation -> Data checks -> Reconcile
                    |
                    v
        Prune workbook -> Re-apply formatting
```

Excel is the working surface. SQLite is the permanent record. Every step is a hard gate: if one fails, nothing after it runs, so the workbook is never pruned after a failed check.

## Quick start (Windows)

Open **Command Prompt** in the project folder. Command Prompt needs backslashes in paths:

```bat
cd C:\Users\<you>\Documents\market_db
venv\Scripts\activate
python ops/run_all.py
```

(PowerShell: `.\venv\Scripts\Activate.ps1`.) You should see `(venv)` at the start of the prompt.

First-time setup:

```bat
py -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
```

## The daily pipeline, step by step

`python ops/run_all.py` runs these in order and stops at the first failure:

| Step | Script | What it does |
|---|---|---|
| 0 | `pytest` | Runs the full test suite first, so a broken code change never touches your data. |
| 1 | `ops/backup.py` | Verified SQLite backup (SQLite backup API + integrity check) and a workbook copy. Keeps the newest 14 of each. |
| 1b | `ops/validate_excel.py` | **Checks the workbook before import.** Read-only. |
| 2 | `ingest/migrate_from_excel.py` | Imports Excel into SQLite, filling blanks and never overwriting existing values. Anything it cannot load is logged to `data_quality_issues`. |
| 3 | `ops/validate_db.py` | SQLite integrity, foreign keys, orphan dates, text hidden in numeric columns, logged issues, holiday-file health. |
| 3b | `ops/data_checks.py` | Calendar-aware completeness, freshness, OHLC logic, plausibility ranges, daily-move limit. |
| 4 | `ops/reconcile.py` | Proves every workbook row about to be pruned is fully present in SQLite. |
| 5 | `ops/prune_excel.py` | Trims the workbook to the latest 15 distinct dates (history stays in SQLite). |
| 6 | `ops/apply_excel_formatting.py` | Re-applies drop-downs, validation and formulas. |

**Do not bypass a failed step to make the pipeline finish.** Read the message, fix the cause, rerun.

## The checks

Findings are labelled **BLOCK** (stops the pipeline), **WARN** (look at it; pipeline continues) or **INFO** (context).

### Before import: `ops/validate_excel.py`

| Level | Check |
|---|---|
| BLOCK | Required `DailyData` headers present |
| BLOCK | Every date readable (real Excel date or `YYYY-MM-DD`; `YYYY/MM/DD` and `YYYY-M-D` are accepted) |
| BLOCK | No duplicate dates |
| BLOCK | No text in numeric cells (e.g. `TBD`) |
| BLOCK | Open/high/low/close are internally consistent for Nifty and VIX |
| BLOCK | `sector_return_pct` is a number or `NA`/blank |
| BLOCK | `confirmed_holidays.json` entries are readable |
| WARN | Date cell carries a time of day (the time is dropped on import) |
| WARN | Dates stored as text mixed with real dates |
| WARN | Weekend dates, or data on a date listed as a holiday |

Ambiguous dates such as `31-08-2026` or a bare number are **not guessed**; they are rejected so you can fix them.

### After import: `ops/validate_db.py`

SQLite `integrity_check` and `foreign_key_check`; `daily_data` not empty; sectors/events with no matching trading day; any row in `data_quality_issues`; text stored in numeric columns (for example an empty string in a REAL column, which the fill-the-blanks import can never replace); holiday-file health.

### Professional data checks: `ops/data_checks.py`

| Level | Check |
|---|---|
| BLOCK | Every expected trading day (weekday minus holiday calendar) has a row |
| BLOCK | Holiday calendar covers every year present in the data |
| BLOCK | OHLC logic: high is the highest, low is the lowest, all prices above zero |
| BLOCK | Values inside sane ranges (Nifty, VIX, Brent, USD/INR, US 10-year yield, PCR) |
| BLOCK | `abs(nifty_change_pct)` above 12% (likely a typo, wrong unit or missing day) |
| WARN | A row on a weekend or listed holiday |
| WARN | Latest row is behind the latest closed trading day |
| INFO | Older rows with empty hand-entered fields (FII/DII, breadth, bias) |

`nifty_change_pts` is an index-point move and can be any size, so it is never range-checked. The 12% limit and the plausibility ranges live at the top of `ops/data_checks.py` (`MAX_DAILY_NIFTY_MOVE_PCT`, `RANGES`) and can be adjusted.

## Holiday calendar

A date is treated as a market holiday if **either** source lists it:

1. **`data/excel_autofetch/nse_holidays.csv`** is the calendar of record. It holds the full NSE list for the year (weekday and weekend holidays) with a `verified` column. Update it once a year from the NSE circular.
2. **`data/excel_autofetch/confirmed_holidays.json`** holds ad-hoc additions, such as a surprise closure.

`ops/trading_calendar.py` merges both. Rules:

- A trading day with no row **blocks** the pipeline.
- A row on a holiday only **warns**, because special sessions (such as Muhurat trading) do happen.
- A year in your data that is missing from the calendar **blocks**, so you cannot forget the January refresh.
- One malformed holiday entry is reported and skipped. It never wipes the valid ones.

Dates must be written `YYYY-MM-DD`. The 2026 calendar was checked against the NSE list.

> **Note:** the daily updater (`data/excel_autofetch/daily_update.py`) reads only `confirmed_holidays.json` when deciding which days to queue. A holiday that is only in the CSV is still understood by validation, but the updater will try that date once per run and skip it when Yahoo returns no data. To make the updater skip a holiday immediately, also add it to `confirmed_holidays.json`.

## Project structure

```text
market_db/
├── config.py                        # Paths, tickers, field mappings, thresholds for the updater
├── requirements.txt
├── pytest.ini
├── data/
│   ├── market.db                    # SQLite database (permanent history)
│   ├── backups/                     # Timestamped recovery copies (newest 14 kept)
│   └── excel_autofetch/
│       ├── Market_Database.xlsx     # Working workbook (latest 15 trading days)
│       ├── nse_holidays.csv         # Holiday calendar of record
│       ├── confirmed_holidays.json  # Ad-hoc holiday additions
│       ├── holiday_state.py         # Tolerant holiday-file reader
│       ├── daily_update.py          # Automated catch-up update engine
│       ├── data_source.py           # Yahoo Finance reader
│       ├── excel_ops.py             # Workbook operations
│       ├── update_daily_data.py     # Entry point for the daily update
│       └── run_log.txt              # Runtime log
├── ingest/
│   ├── schema.sql                   # Table definitions
│   └── migrate_from_excel.py        # Excel -> SQLite import
├── ops/
│   ├── run_all.py                   # The guarded pipeline
│   ├── backup.py
│   ├── validate_excel.py            # Pre-import workbook check
│   ├── validate_db.py               # Database validation
│   ├── data_checks.py               # Professional data checks
│   ├── trading_calendar.py          # Holiday-aware trading-day logic
│   ├── reconcile.py
│   ├── prune_excel.py
│   ├── apply_excel_formatting.py
│   ├── convert_sector_return_to_real.py   # One-time conversion (already applied)
│   └── ...                          # Table-check and maintenance utilities
├── analysis/                        # Drawdowns, sector rotation, global linkage, dashboard
├── journal/export.py                # Journal CSV export
└── tests/                           # 76 automated tests
```

## Database tables

Dates are stored as ISO text (`YYYY-MM-DD`). Binary flags are stored as 0/1/NULL.

| Table | Purpose |
|---|---|
| `daily_data` | One row per trading day: Nifty, VIX, FII/DII, derivatives, macro inputs, journal fields |
| `market_vibe` | Global-market context and sentiment by date |
| `sector_list` | Reference list of permitted sector names |
| `sectors` | Sector observations by date; `sector_return_pct` is `REAL` (NULL when Excel has `NA` or blank) |
| `events` | Market-moving events with direction and magnitude |
| `learnings` | Personal lessons and action notes |
| `metadata` | Key/value notes about the database |
| `data_quality_issues` | Rows that could not be imported confidently, kept for review |

## Useful commands

Run from the project root with the virtual environment active.

| Purpose | Command |
|---|---|
| Run the whole guarded pipeline | `python ops/run_all.py` |
| Run all tests | `python -m pytest -q` |
| Check the workbook before importing | `python ops/validate_excel.py` |
| Validate the database | `python ops/validate_db.py` |
| Run the professional data checks | `python ops/data_checks.py` |
| Create and verify backups | `python ops/backup.py` |
| Reconcile workbook against database | `python ops/reconcile.py` |
| Export journal CSVs | `python journal/export.py` |

## Safeguards and recovery

- Tests run before anything touches data. Backups run before any change.
- The import never overwrites an existing database value and never silently drops a row; unloadable rows go to `data_quality_issues`.
- Validation and the Excel pre-check are read-only.
- Reconciliation proves rows are safe in SQLite before the workbook is pruned.
- Do not delete rows from the database to silence a check. Review `data_quality_issues` and decide.
- Keep an independent copy of `data/backups/` if you need history beyond the newest 14.
- Before changing schema, headers, retention or import logic, copy the project and test there.

To restore, close Excel, then copy a backup from `data/backups/` over `data/market.db` (or the workbook).

## Troubleshooting

| Symptom | What to do |
|---|---|
| `'venv' is not recognized` | Command Prompt needs backslashes: `venv\Scripts\activate` |
| Stops at the test step | Run `python -m pytest -q` and read the first failure |
| `[PROBLEM] ... unreadable date` | Fix that workbook row to a real date or `YYYY-MM-DD`; day-first text is never guessed |
| `[PROBLEM] ... holds text ''` | Text is stuck in a numeric column. The message prints the exact `UPDATE ... SET col = NULL` to run, after a backup. Run it with Python or the `sqlite3` tool, **not MySQL Workbench** (this is SQLite) |
| `expected trading day but has no row` | Either data is missing (run the daily update) or it was a holiday (add it to the calendar) |
| `no holidays listed for [year]` | Add that year to `nse_holidays.csv` |
| Workbook locked / will not save | Close Excel completely, including background processes |
| A market value looks wrong or missing | Check the source, trading date, market-close timing and whether Yahoo publishes it that day |

## Design rules to know about

These are intentional, so they are not errors:

- **The sync is one-way and fill-only.** Importing fills empty database cells but does not update filled ones, so correcting an already-imported value in Excel will not change SQLite. For sectors, events and learnings, rows are inserted if new and otherwise left alone.
- **The workbook keeps only 15 trading days.** Once a row is pruned, you cannot fill its empty manual fields from Excel. Complete journal fields (FII/DII, breadth, bias) before the row ages out.
- **Some older closes are whole numbers** (typed by hand), so their stored change values differ slightly from close-to-close.
- **`market_vibe` and `daily_data` both hold Brent, USD/INR and the US 10-year yield** and can differ because they come from different sources.
- **Two date cells in the current workbook carry a time of day** (19 Oct and 21 Oct 2026). Harmless; new rows are written at midnight.

## Yearly and one-time tasks

- **Every January:** add the new year's NSE holidays to `nse_holidays.csv` and mark them `verified = yes` once checked.
- **One-time, already applied:** `ops/convert_sector_return_to_real.py` converted `sectors.sector_return_pct` from text to numbers (safe to re-run; it reports "already REAL").

## Maintenance principles

1. Preserve data first.
2. Test before modifying records.
3. Back up before maintenance.
4. Validate before pruning source history.
5. Keep uncertain imports visible for review rather than silently discarding them.
6. Prefer small, reversible changes over destructive fixes.

---

*Personal learning and research project. Update this README whenever the pipeline, paths, schema or commands change.*
