"""Deterministic completed-bar feature kernel for AETHER HELD_OUT replay.

This module converts one already-normalized, point-in-time bar history into only the
source-bound numerical facts needed by downstream Family evaluators.

It deliberately does NOT:
- choose a playbook reference-range lookback;
- calculate realized-volatility percentile rank;
- infer event/counter-trend state;
- infer equity locate/borrow state;
- create trades, fills, or evidence.

All supplied bars must already be completed and available by as_of_utc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from aether_vnext.bar_features import (
    PriorClosedBarRange,
    prior_closed_bar_range,
)
from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import (
    INDICATOR_CONVENTION_VERSION,
    atr14,
    ema20,
    ema50,
    realized_vol14,
)


@dataclass(frozen=True, slots=True)
class ClosedBarFeatureSnapshot:
    asset_id: str
    interval: timedelta
    as_of_utc: datetime
    bar_count: int
    trigger_bar: Bar
    close: float
    ema20_current: float
    ema20_previous: float
    ema50_current: float
    atr14_current: float
    realized_vol14_current: float
    prior_range: PriorClosedBarRange | None
    indicator_convention_version: str = INDICATOR_CONVENTION_VERSION


def build_closed_bar_feature_snapshot(
    bars: Sequence[Bar],
    *,
    as_of_utc: datetime,
    prior_range_lookback: int | None = None,
) -> ClosedBarFeatureSnapshot:
    """Build one no-lookahead numerical feature snapshot.

    EMA/ATR state is calculated across the complete supplied history using the
    operator-approved Indicator Convention v1. The caller therefore owns the
    historical warm-up window; this function never truncates or invents one.
    """
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    rows = tuple(bars)
    if len(rows) < 50:
        raise ValueError(
            "at least 50 completed bars are required for the replay feature snapshot"
        )

    for bar in rows:
        if bar.bucket_open_utc.tzinfo is None or bar.bucket_close_utc.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if bar.first_exchange_ts.tzinfo is None or bar.last_exchange_ts.tzinfo is None:
            raise ValueError("bar exchange timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("bars must be completed")
        if bar.last_exchange_ts >= bar.bucket_close_utc:
            raise ValueError(
                "forming/incomplete bar cannot enter replay features"
            )
        if bar.bucket_close_utc > as_of_utc:
            raise ValueError("future bar cannot enter replay features")

    range_result: PriorClosedBarRange | None = None
    if prior_range_lookback is not None:
        lookback = int(prior_range_lookback)
        if lookback <= 0:
            raise ValueError("prior_range_lookback must be positive")
        range_result = prior_closed_bar_range(
            rows,
            lookback_bars=lookback,
        )

    trigger = rows[-1]
    return ClosedBarFeatureSnapshot(
        asset_id=trigger.asset_id,
        interval=trigger.interval,
        as_of_utc=as_of_utc,
        bar_count=len(rows),
        trigger_bar=trigger,
        close=float(trigger.close),
        ema20_current=ema20(rows),
        ema20_previous=ema20(rows[:-1]),
        ema50_current=ema50(rows),
        atr14_current=atr14(rows),
        realized_vol14_current=realized_vol14(rows),
        prior_range=range_result,
    )
