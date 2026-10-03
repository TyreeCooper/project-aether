"""Structural contract for pure completed-bar research calculations.

This contract intentionally excludes exchange-print timestamps. Indicator/range math
needs completed bucket geometry and OHLC facts only. Live runtime safety continues to
use the stricter Bar contract with exchange timestamps.

Research adapters may implement this protocol from immutable PIT warehouse records
without fabricating live-market fields.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol


class CompletedOHLCBar(Protocol):
    asset_id: str
    interval: timedelta
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
