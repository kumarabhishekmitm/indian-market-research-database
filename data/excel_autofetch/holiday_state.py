"""
holiday_state.py
-----------------
A tiny, human-readable JSON file recording calendar dates that have been
CONFIRMED (via live data evidence — see data_source.FetchResult) to be non
-trading days for NSE (weekday holidays). This exists purely so that once a
holiday has been confirmed, the script doesn't ask the same "is X a trading
day?" question forever on every subsequent run — it can just skip past
already-confirmed holidays without hitting the network again.

This file is NEVER used to assume a date is a holiday ahead of time. Dates
only get added here after live data has proven they were skipped by the
exchange (see the "has_bars_after_target_date" logic in data_source.py).

Safe to delete this file at any time — worst case, the script re-checks a
date it had already confirmed, which costs one extra API call, not any data
integrity risk.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import List, Set, Tuple


_LOOSE_DATE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")


def parse_date(text) -> dt.date:
    """Parse 'YYYY-MM-DD' (also tolerates 'YYYY-M-D' and 'YYYY/MM/DD').

    Raises ValueError for anything that is not a real calendar date.
    """
    m = _LOOSE_DATE.match(str(text).strip())
    if not m:
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def load_with_problems(path: Path) -> Tuple[Set[dt.date], List[str]]:
    """Return (valid holidays, human-readable problems).

    Each entry is parsed on its own: ONE bad entry is reported and skipped,
    it never discards the good ones. (Previously a single typo such as
    "2026-10-2" made the whole set come back empty, silently.)
    """
    if not path.exists():
        return set(), []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # A damaged state file must never crash the run or corrupt the
        # workbook - treat it as empty, but SAY so.
        return set(), [f"{path.name} could not be read: {e}"]

    entries = raw.get("confirmed_holidays") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return set(), [f"{path.name} must contain a 'confirmed_holidays' list"]

    good: Set[dt.date] = set()
    problems: List[str] = []
    for item in entries:
        try:
            parsed = parse_date(item)
        except (ValueError, TypeError):
            problems.append(f"entry {item!r} is not a valid date and was IGNORED")
            continue
        if str(item).strip() != parsed.isoformat():
            problems.append(f"entry {item!r} accepted but should be written {parsed.isoformat()}")
        good.add(parsed)
    return good, problems


def load(path: Path) -> Set[dt.date]:
    return load_with_problems(path)[0]


def add(path: Path, date: dt.date) -> None:
    dates = load(path)
    dates.add(date)
    payload = {"confirmed_holidays": sorted(d.isoformat() for d in dates)}
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass  # non-critical: worst case we re-confirm this date next time
