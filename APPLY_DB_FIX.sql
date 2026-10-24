-- Run once on data/market.db (after ops/backup.py)
UPDATE daily_data SET advance_decline_ratio = NULL WHERE date = '2026-10-19';
