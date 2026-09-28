"""Point-in-time trend features for source-bound AETHER playbook requirements.

The trend timeframe/rule comes from playbook_trend_requirements. This module computes
only that trend state from supplied completed bars using Indicator Convention v1.

It never resamples bars, invents a timeframe, infers dependency state, selects a
playbook, or creates research evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import (
    INDICATOR_CONVENTION_VERSION,
    ema20,
    ema50,
)
from aether_vnext.playbook_trend_requirements import (
    TrendRuleKind,
    trend_requirement,
)


@dataclass(frozen=True, slots=True)
class PlaybookTrendFeatureSnapshot:
    playbook_id: str
    asset_id: str
    interval: timedelta
    as_of_utc: datetime
    source_bar_count: int
    last_bar_close_utc: datetime
    rule_kind: TrendRuleKind
    ema20_current: float
    ema20_previous: float | None
    ema50_current: float | None
    indicator_convention_version: str = INDICATOR_CONVENTION_VERSION


def _validate_pit_rows(
    bars: Sequence[Bar],
    *,
    required_interval: timedelta,
    as_of_utc: datetime,
    minimum: int,
) -> tuple[Bar, ...]:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    rows = tuple(bars)
    if len(rows) < minimum:
        raise ValueError(
            f"at least {minimum} completed trend bars are required"
        )

    for bar in rows:
        if bar.interval != required_interval:
            raise ValueError(
                "trend bar interval does not match playbook requirement"
            )
        if (
            bar.bucket_open_utc.tzinfo is None
            or bar.bucket_close_utc.tzinfo is None
            or bar.first_exchange_ts.tzinfo is None
            or bar.last_exchange_ts.tzinfo is None
        ):
            raise ValueError("trend bar timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("trend bars must be completed")
        if bar.last_exchange_ts >= bar.bucket_close_utc:
            raise ValueError(
                "forming/incomplete bar cannot enter trend features"
            )
        if bar.bucket_close_utc > as_of_utc:
            raise ValueError("future bar cannot enter trend features")

    return rows


def build_playbook_trend_features(
    playbook_id: str,
    bars: Sequence[Bar],
    *,
    as_of_utc: datetime,
) -> PlaybookTrendFeatureSnapshot:
    """Compute the source-bound trend facts for one executable Family-A playbook."""
    requirement = trend_requirement(playbook_id)
    minimum = (
        21
        if requirement.rule_kind is TrendRuleKind.EMA20_SLOPE
        else 50
    )
    rows = _validate_pit_rows(
        bars,
        required_interval=requirement.interval,
        as_of_utc=as_of_utc,
        minimum=minimum,
    )

    current = ema20(rows)
    if requirement.rule_kind is TrendRuleKind.EMA20_SLOPE:
        previous = ema20(rows[:-1])
        slow = None
    elif requirement.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL:
        previous = None
        slow = ema50(rows)
    else:
        raise ValueError("unsupported playbook trend rule")

    return PlaybookTrendFeatureSnapshot(
        playbook_id=requirement.playbook_id,
        asset_id=rows[-1].asset_id,
        interval=requirement.interval,
        as_of_utc=as_of_utc,
        source_bar_count=len(rows),
        last_bar_close_utc=rows[-1].bucket_close_utc,
        rule_kind=requirement.rule_kind,
        ema20_current=current,
        ema20_previous=previous,
        ema50_current=slow,
    )
