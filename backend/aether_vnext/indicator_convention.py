"""Operator-approved AETHER Indicator Convention v1.

This module resolves the calculation-convention gaps left intentionally unbound by
the frozen Master/Playbook source set. The formulas here are an explicit operator
specification decision approved on 2026-09-27; they are not attributed back to the
source documents.

All inputs are completed bars. No forming/future bar may enter these calculations.
"""
from __future__ import annotations

from math import isfinite, log, sqrt
from typing import Final, Sequence

from aether_vnext.completed_bar_contract import CompletedOHLCBar


INDICATOR_CONVENTION_VERSION: Final = "aether_indicator_convention_v1"


def _validate_bars(bars: Sequence[CompletedOHLCBar], *, minimum: int) -> tuple[CompletedOHLCBar, ...]:
    rows = tuple(bars)
    if len(rows) < minimum:
        raise ValueError(f"at least {minimum} completed bars are required")

    asset_id = rows[0].asset_id
    interval = rows[0].interval
    prior_open = None
    prior_close = None

    for bar in rows:
        if bar.asset_id != asset_id:
            raise ValueError("all bars must share asset_id")
        if bar.interval != interval:
            raise ValueError("all bars must share interval")
        if bar.bucket_open_utc.tzinfo is None or bar.bucket_close_utc.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("bars must be completed")

        prices = (
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
        )
        if not all(isfinite(value) and value > 0.0 for value in prices):
            raise ValueError("OHLC prices must be finite and positive")
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise ValueError("OHLC prices are internally inconsistent")
        if bar.high < bar.low:
            raise ValueError("bar high cannot be below bar low")

        if prior_open is not None and bar.bucket_open_utc <= prior_open:
            raise ValueError("bars must be strictly ordered")
        if prior_close is not None and bar.bucket_close_utc <= prior_close:
            raise ValueError("bar closes must be strictly ordered")
        prior_open = bar.bucket_open_utc
        prior_close = bar.bucket_close_utc

    return rows


def _ema(bars: Sequence[CompletedOHLCBar], *, period: int) -> float:
    """SMA-seeded recursive EMA over completed bar closes."""
    rows = _validate_bars(bars, minimum=period)
    closes = tuple(float(bar.close) for bar in rows)

    value = sum(closes[:period]) / float(period)
    alpha = 2.0 / float(period + 1)
    for close in closes[period:]:
        value = alpha * close + (1.0 - alpha) * value
    return value


def ema20(bars: Sequence[CompletedOHLCBar]) -> float:
    """EMA20: SMA(20) seed, then alpha=2/(20+1), closed-bar closes only."""
    return _ema(bars, period=20)


def ema50(bars: Sequence[CompletedOHLCBar]) -> float:
    """EMA50: SMA(50) seed, then alpha=2/(50+1), closed-bar closes only."""
    return _ema(bars, period=50)


def atr14(bars: Sequence[CompletedOHLCBar]) -> float:
    """Wilder ATR14 using 14 true-range observations.

    The first ATR is the arithmetic mean of the first 14 true ranges. Later
    observations use Wilder smoothing: (13 * prior_atr + current_tr) / 14.
    """
    rows = _validate_bars(bars, minimum=15)
    true_ranges: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        previous_close = float(previous.close)
        true_ranges.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - previous_close),
                abs(float(current.low) - previous_close),
            )
        )

    value = sum(true_ranges[:14]) / 14.0
    for true_range in true_ranges[14:]:
        value = ((13.0 * value) + true_range) / 14.0
    return value


def realized_vol14(bars: Sequence[CompletedOHLCBar]) -> float:
    """Non-annualized 14-return realized volatility on completed closes.

    RV14 = sqrt(sum(r_t**2)) for the trailing 14 log returns, where
    r_t = ln(close_t / close_{t-1}).
    """
    rows = _validate_bars(bars, minimum=15)
    trailing = rows[-15:]
    squared_returns = 0.0
    for previous, current in zip(trailing, trailing[1:]):
        return_ = log(float(current.close) / float(previous.close))
        squared_returns += return_ * return_
    return sqrt(squared_returns)
