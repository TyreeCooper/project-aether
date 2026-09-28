"""Operator-approved AETHER Volatility Percentile Convention v1.

The frozen Playbook Pack requires RV14 at the trigger interval to be compared with
the percentile distribution from the prior 90 calendar days of that same interval,
but does not bind a rank/tie/interpolation convention.

The operator delegated that missing convention on 2026-09-27. AETHER binds it as:
- reference evaluation timestamps in [T - 90 calendar days, T);
- same asset and same interval only;
- current trigger RV14 excluded from its own reference distribution;
- each historical RV14 calculated point-in-time from data available at that
  historical completed-bar close;
- empirical midrank percentile:
      100 * (count(reference < current) + 0.5 * count(reference == current)) / N
- no interpolation and no pre-classification rounding;
- N == 0 fails closed;
- enough pre-window bars must exist to warm RV14 at the start of the 90-day window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Final, Sequence

from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import realized_vol14


VOLATILITY_PERCENTILE_CONVENTION_VERSION: Final = (
    "aether_volatility_percentile_convention_v1"
)
VOLATILITY_PERCENTILE_WINDOW: Final = timedelta(days=90)
RV14_REQUIRED_CLOSES: Final = 15


@dataclass(frozen=True, slots=True)
class VolatilityPercentileSnapshot:
    asset_id: str
    interval: timedelta
    trigger_close_utc: datetime
    window_start_utc: datetime
    window_end_exclusive_utc: datetime
    current_realized_vol14: float
    reference_count: int
    less_count: int
    equal_count: int
    percentile: float
    convention_version: str = VOLATILITY_PERCENTILE_CONVENTION_VERSION


def empirical_midrank_percentile(
    current: float,
    reference: Sequence[float],
) -> tuple[float, int, int]:
    value = float(current)
    if not isfinite(value) or value < 0.0:
        raise ValueError("current volatility must be finite and nonnegative")

    rows = tuple(float(item) for item in reference)
    if not rows:
        raise ValueError("reference distribution cannot be empty")
    if any(not isfinite(item) or item < 0.0 for item in rows):
        raise ValueError(
            "reference volatility values must be finite and nonnegative"
        )

    less = sum(item < value for item in rows)
    equal = sum(item == value for item in rows)
    percentile = 100.0 * (less + 0.5 * equal) / float(len(rows))
    return percentile, less, equal


def realized_vol14_percentile_90d(
    bars: Sequence[Bar],
    *,
    as_of_utc: datetime,
) -> VolatilityPercentileSnapshot:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    rows = tuple(bars)
    if len(rows) < RV14_REQUIRED_CLOSES:
        raise ValueError(
            "at least 15 completed bars are required for RV14 percentile"
        )

    current_rv = realized_vol14(rows)
    trigger = rows[-1]

    for bar in rows:
        if (
            bar.bucket_open_utc.tzinfo is None
            or bar.bucket_close_utc.tzinfo is None
            or bar.first_exchange_ts.tzinfo is None
            or bar.last_exchange_ts.tzinfo is None
        ):
            raise ValueError("bar timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("bars must be completed")
        if bar.last_exchange_ts >= bar.bucket_close_utc:
            raise ValueError(
                "forming/incomplete bar cannot enter volatility percentile"
            )
        if bar.bucket_close_utc > as_of_utc:
            raise ValueError(
                "future bar cannot enter volatility percentile"
            )

    trigger_close = trigger.bucket_close_utc
    window_start = trigger_close - VOLATILITY_PERCENTILE_WINDOW

    pre_window = tuple(
        bar for bar in rows[:-1]
        if bar.bucket_close_utc <= window_start
    )
    if len(pre_window) < RV14_REQUIRED_CLOSES:
        raise ValueError(
            "insufficient pre-window RV14 warm-up for complete 90-day reference"
        )

    reference: list[float] = []
    for end_index in range(RV14_REQUIRED_CLOSES - 1, len(rows) - 1):
        evaluation_close = rows[end_index].bucket_close_utc
        if not (window_start <= evaluation_close < trigger_close):
            continue
        start_index = end_index - (RV14_REQUIRED_CLOSES - 1)
        reference.append(
            realized_vol14(rows[start_index : end_index + 1])
        )

    percentile, less, equal = empirical_midrank_percentile(
        current_rv,
        reference,
    )
    return VolatilityPercentileSnapshot(
        asset_id=trigger.asset_id,
        interval=trigger.interval,
        trigger_close_utc=trigger_close,
        window_start_utc=window_start,
        window_end_exclusive_utc=trigger_close,
        current_realized_vol14=current_rv,
        reference_count=len(reference),
        less_count=less,
        equal_count=equal,
        percentile=percentile,
    )
