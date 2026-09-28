"""Source-bound closed-bar range features for AETHER vNext.

These helpers derive only range facts explicitly defined by the Playbook Pack.
They do not choose lookback lengths on their own and do not calculate EMA/ATR/
volatility conventions that are not supplied here.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.completed_bar_contract import CompletedOHLCBar


@dataclass(frozen=True, slots=True)
class PriorClosedBarRange:
    asset_id: str
    lookback_bars: int
    high: float
    low: float
    mid: float
    first_bar: CompletedOHLCBar
    last_bar: CompletedOHLCBar


def prior_closed_bar_range(
    bars: tuple[CompletedOHLCBar, ...],
    *,
    lookback_bars: int,
) -> PriorClosedBarRange:
    """Return the range of N bars immediately preceding the trigger bar.

    The final input bar is the current completed trigger bar and is deliberately
    excluded from the reference range to prevent same-bar lookahead.
    """
    lookback = int(lookback_bars)
    if lookback <= 0:
        raise ValueError("lookback_bars must be positive")
    if len(bars) < lookback + 1:
        raise ValueError(
            "insufficient completed bars for prior range plus trigger bar"
        )

    trigger = bars[-1]
    reference = bars[-(lookback + 1) : -1]

    asset_id = trigger.asset_id
    interval = trigger.interval
    prior_open = None
    prior_close = None
    for bar in (*reference, trigger):
        if bar.asset_id != asset_id:
            raise ValueError("all bars must share asset_id")
        if bar.interval != interval:
            raise ValueError("all bars must share interval")
        if bar.bucket_open_utc.tzinfo is None or bar.bucket_close_utc.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("bars must be closed")
        if prior_open is not None and bar.bucket_open_utc <= prior_open:
            raise ValueError("bars must be strictly ordered")
        if prior_close is not None and bar.bucket_close_utc <= prior_close:
            raise ValueError("bar closes must be strictly ordered")
        prior_open = bar.bucket_open_utc
        prior_close = bar.bucket_close_utc

    high = max(float(bar.high) for bar in reference)
    low = min(float(bar.low) for bar in reference)
    if high <= 0 or low <= 0 or high < low:
        raise ValueError("prior range prices are invalid")

    return PriorClosedBarRange(
        asset_id=asset_id,
        lookback_bars=lookback,
        high=high,
        low=low,
        mid=(high + low) / 2.0,
        first_bar=reference[0],
        last_bar=reference[-1],
    )
