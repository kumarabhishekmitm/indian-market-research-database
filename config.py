r"""
config.py
---------
SINGLE SOURCE OF TRUTH for the entire market database pipeline.
"""

import sys
from pathlib import Path

# Absolute path enforcement to prevent CWD-dependent bugs
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# File and Database Paths
EXCEL_FILE_NAME = "Market_Database.xlsx"
EXCEL_PATH = PROJECT_ROOT / "data" / "excel_autofetch" / EXCEL_FILE_NAME

DB_PATH = PROJECT_ROOT / "data" / "market.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DB_PATH_STR = str(DB_PATH)  # Universal string bridge for sqlite3 connections & tests

STATE_DIR = EXCEL_PATH.parent
CONFIRMED_HOLIDAYS_FILE = STATE_DIR / "confirmed_holidays.json"
LOG_FILE = STATE_DIR / "run_log.txt"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

KEEP_BACKUPS = 14
MARKET_TIMEZONE = "Asia/Kolkata"
# Do not accept "today's" bar before this IST time (NSE closes 15:30).
MARKET_CLOSE_TIME = (15, 45)  # (hour, minute)

# Excel Structure
SHEET_NAME = "DailyData"
TABLE_NAME = "DailyData__2"

PRUNE_TARGETS = {
    "DailyData": "DailyData__2",
    # Add any other sheets and their table names here as needed
}

# Tickers & Schema
TICKERS = {
    "nifty": "^NSEI",
    "vix": "^INDIAVIX",
    "brent": "BZ=F",
    "usdinr": "INR=X",
    "us10y": "^TNX",
}

PRIMARY_TICKER = "nifty"

AUTO_FIELD_MAP = {
    "nifty_open": ("nifty", "open"),
    "nifty_high": ("nifty", "high"),
    "nifty_low": ("nifty", "low"),
    "nifty_close": ("nifty", "close"),
    "vix_open": ("vix", "open"),
    "vix_high": ("vix", "high"),
    "vix_low": ("vix", "low"),
    "vix_close": ("vix", "close"),
    "brent_crude": ("brent", "close"),
    "usd_inr": ("usdinr", "close"),
    "us_10y_yield": ("us10y", "close"),
}

DERIVED_COLUMNS = ["nifty_change_pts", "nifty_change_pct", "nifty_gap_pts", "vix_change_pct"]
OHLC_TICKERS = ["nifty", "vix"]

MANUAL_COLUMNS = {
    "fii_equity_cr": "NSE/NSDL FII-DII daily provisional data",
    "dii_equity_cr": "NSE/NSDL FII-DII daily provisional data",
    "fii_index_futures_cr": "NSE FII derivatives statistics",
    "fii_index_options_cr": "NSE FII derivatives statistics",
    "fii_stock_futures_cr": "NSE FII derivatives statistics",
    "pcr_value": "NSE option chain (Nifty PCR)",
    "pcr_type": "Your read: WEEKLY / MONTHLY",
    "resistance_imm": "Your technical analysis",
    "resistance_max": "Your technical analysis",
    "support_imm": "Your technical analysis",
    "support_max": "Your technical analysis",
    "advance_count": "NSE market breadth (advances)",
    "decline_count": "NSE market breadth (declines)",
    "emotional_state": "Your trading journal entry",
    "tomorrow_bias": "Your trading journal entry",
    "prediction_hit": "Fill in the NEXT day, once you know if your bias was right",
}

FORMULA_COLUMNS = {
    "advance_decline_ratio": (
        "={table}[[#This Row],[advance_count]]/{table}[[#This Row],[decline_count]]"
    ),
}

REQUIRED_HEADERS = ["date"] + list(AUTO_FIELD_MAP.keys()) + DERIVED_COLUMNS + list(MANUAL_COLUMNS.keys())
NA_VALUES = {"na", "n/a", "-", "", "null", "none"}