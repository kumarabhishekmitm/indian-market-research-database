-- schema.sql
-- Defines all tables for the market research database.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS everywhere.

PRAGMA foreign_keys = ON;

-- Reference list of valid sector names (from the "Lists" sheet)
CREATE TABLE IF NOT EXISTS sector_list (
    sector_name TEXT PRIMARY KEY
);

-- One row per trading day, Nifty/VIX/FII-DII/etc.
CREATE TABLE IF NOT EXISTS daily_data (
    date                    TEXT PRIMARY KEY,   -- ISO format YYYY-MM-DD
    nifty_open              REAL,
    nifty_high              REAL,
    nifty_low               REAL,
    nifty_close             REAL,
    nifty_change_pts        REAL,
    nifty_change_pct        REAL,
    vix_open                REAL,
    vix_high                REAL,
    vix_low                 REAL,
    vix_close               REAL,
    vix_change_pct          REAL,
    fii_equity_cr           REAL,
    dii_equity_cr           REAL,
    fii_index_futures_cr    REAL,
    fii_index_options_cr    REAL,
    fii_stock_futures_cr    REAL,
    pcr_value               REAL,
    pcr_type                TEXT,
    resistance_imm          REAL,
    resistance_max          REAL,
    support_imm             REAL,
    support_max             REAL,
    advance_count           INTEGER,
    decline_count           INTEGER,
    advance_decline_ratio   REAL,
    nifty_gap_pts           REAL,
    emotional_state         TEXT,
    tomorrow_bias           TEXT,
    prediction_hit          INTEGER,   -- 0/1/NULL, since SQLite has no true boolean
    brent_crude             REAL,
    usd_inr                 REAL,
    us_10y_yield            REAL
);

-- One row per trading day, global market sentiment
CREATE TABLE IF NOT EXISTS market_vibe (
    date                TEXT PRIMARY KEY,
    us_sp500_pct        REAL,
    us_nasdaq_pct       REAL,
    gift_nifty_pct      REAL,
    brent_crude         REAL,
    usd_inr             REAL,
    us_10y_yield        REAL,
    asian_market        TEXT,
    market_vibe_label   TEXT,
    confidence_score    INTEGER
);

-- Multiple rows per day: one per sector
CREATE TABLE IF NOT EXISTS sectors (
    sector_id           INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,
    sector_name         TEXT NOT NULL,
    performance         TEXT,          -- e.g. TOP_GAINER / TOP_LOSER
    sector_return_pct   REAL,          -- percent return; NULL when Excel has 'NA' or blank
    FOREIGN KEY (sector_name) REFERENCES sector_list(sector_name)
);

-- Multiple rows per day: market-moving events
CREATE TABLE IF NOT EXISTS events (
    event_id            INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,
    event_type          TEXT,
    event_category      TEXT,
    event_description   TEXT,
    impact_direction    TEXT,          -- BULLISH / BEARISH / NEUTRAL
    impact_magnitude    INTEGER
);

-- Multiple rows per day: your personal lessons/journal entries
CREATE TABLE IF NOT EXISTS learnings (
    learning_id      INTEGER PRIMARY KEY,
    date             TEXT NOT NULL,
    lesson_priority  INTEGER,
    lesson_text      TEXT,
    lesson_category  TEXT,
    actionable       INTEGER   -- 0/1/NULL
);

-- Key/value settings about the database itself
CREATE TABLE IF NOT EXISTS metadata (
    key      TEXT PRIMARY KEY,
    value    TEXT,
    comment  TEXT
);

-- Every row we could NOT confidently load, preserved for manual review.
-- This is permanent infrastructure, not a one-time cleanup table.
CREATE TABLE IF NOT EXISTS data_quality_issues (
    issue_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sheet       TEXT NOT NULL,
    source_row_number  INTEGER,        -- row number in the original Excel sheet
    issue_description  TEXT NOT NULL,  -- why this row was flagged
    raw_row_data       TEXT,           -- the original row, as text/JSON, for manual review
    logged_at          TEXT NOT NULL,  -- ISO datetime this issue was recorded
    UNIQUE(source_sheet, source_row_number, issue_description)
);