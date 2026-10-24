"""
data_source.py
---------------
Encapsulated, fail-safe market data reader using yfinance.
Resolves timezone boundary mismatches and validates OHLC integrity.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Optional


class DataSourceError(Exception):
    """Base exception for data retrieval issues."""


class NetworkError(DataSourceError):
    """Raised when network connectivity or endpoint fails."""


class MalformedResponseError(DataSourceError):
    """Raised when data structure is invalid or corrupt."""


@dataclass
class DayBar:
    open: float
    high: float
    low: float
    close: float


@dataclass
class FetchResult:
    bar_on_target_date: Optional[DayBar]
    prev_close: Optional[float]
    has_bars_after_target_date: bool


def validate_ohlc(bar: DayBar) -> Optional[str]:
    """Validate mathematical consistency of OHLC bars."""
    try:
        o, h, l, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
    except (TypeError, ValueError):
        return "non-numeric OHLC value"

    for name, v in (("open", o), ("high", h), ("low", l), ("close", c)):
        if v is None or v != v:
            return f"{name} is missing or NaN"
        if v <= 0:
            return f"{name} must be positive (got {v})"

    if h < o or h < c or h < l:
        return f"high ({h}) is less than open ({o}), close ({c}), or low ({l})"
    if l > o or l > c:
        return f"low ({l}) is greater than open ({o}) or close ({c})"

    return None


class YFinanceDataSource:
    """Production live market data source interacting with Yahoo Finance."""

    def fetch_ticker(self, symbol: str, target_date: dt.date) -> FetchResult:
        try:
            import yfinance as yf
        except ImportError as e:
            raise DataSourceError("yfinance is not installed in the environment.") from e

        start = target_date - dt.timedelta(days=15)
        end = target_date + dt.timedelta(days=5)

        try:
            hist = yf.Ticker(symbol).history(
                start=start.isoformat(), end=end.isoformat(), interval="1d"
            )
        except Exception as e:
            raise NetworkError(f"Network request failed for {symbol}: {e}") from e

        if hist is None or not isinstance(hist, object):
            raise MalformedResponseError(f"{symbol}: response was None or invalid")

        required_cols = {"Open", "High", "Low", "Close"}
        if not required_cols.issubset(set(hist.columns)):
            raise MalformedResponseError(
                f"{symbol}: missing expected columns (got {list(hist.columns)})"
            )

        if hist.empty:
            raise MalformedResponseError(
                f"{symbol}: empty dataset returned for window {start} to {end}"
            )

        # Explicit Timezone Normalization to Market Timezone (Asia/Kolkata)
        try:
            if hist.index.tz is not None:
                hist.index = hist.index.tz_convert("Asia/Kolkata").tz_localize(None)
        except Exception:
            try:
                hist.index = hist.index.tz_localize(None)
            except Exception:
                pass

        hist["_date_only"] = hist.index.date

        today_rows = hist[hist["_date_only"] == target_date]
        prior_rows = hist[hist["_date_only"] < target_date]
        after_rows = hist[hist["_date_only"] > target_date]

        bar = None
        if not today_rows.empty:
            r = today_rows.iloc[-1]
            try:
                bar = DayBar(
                    open=float(r["Open"]),
                    high=float(r["High"]),
                    low=float(r["Low"]),
                    close=float(r["Close"]),
                )
            except (TypeError, ValueError) as e:
                raise MalformedResponseError(
                    f"{symbol}: non-numeric OHLC values on {target_date}: {e}"
                ) from e

        prev_close = None
        if not prior_rows.empty:
            prev_close = float(prior_rows.iloc[-1]["Close"])

        return FetchResult(
            bar_on_target_date=bar,
            prev_close=prev_close,
            has_bars_after_target_date=not after_rows.empty,
        )


class MockDataSource:
    """Deterministic Mock Source for unit testing."""

    def __init__(self, plan: Dict[str, dict]):
        self.plan = plan

    def fetch_ticker(self, symbol: str, target_date: dt.date) -> FetchResult:
        import config
        key = next((k for k, v in config.TICKERS.items() if v == symbol), symbol)
        spec = self.plan.get(key, {"mode": "no_data", "has_bars_after": False})
        mode = spec.get("mode", "ok")

        if mode == "network_error":
            raise NetworkError(f"Simulated network error for {symbol}")
        if mode == "malformed":
            raise MalformedResponseError(f"Simulated malformed response for {symbol}")
        if mode == "no_data":
            return FetchResult(
                bar_on_target_date=None,
                prev_close=spec.get("prev_close"),
                has_bars_after_target_date=spec.get("has_bars_after", False),
            )
        return FetchResult(
            bar_on_target_date=spec["bar"],
            prev_close=spec.get("prev_close"),
            has_bars_after_target_date=spec.get("has_bars_after", True),
        )