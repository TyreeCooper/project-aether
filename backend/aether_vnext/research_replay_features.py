"""Research-only replay features from immutable PIT warehouse bars.

This path never fabricates live exchange-print timestamps. It derives the approved
indicator/range/volatility-regime facts directly from ResearchBarRecord rows selected
through the PIT availability boundary.

It does not enter runtime_cycle, create setups, simulate fills, or persist evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from aether_vnext.bar_features import (
    PriorClosedBarRange,
    prior_closed_bar_range,
)
from aether_vnext.indicator_convention import (
    INDICATOR_CONVENTION_VERSION,
    atr14,
    ema20,
    ema50,
    realized_vol14,
)
from aether_vnext.playbook_runtime import (
    VolatilityBand,
    volatility_band,
)
from aether_vnext.research_bar_selection import PITResearchBarSlice
from aether_vnext.research_warehouse import ResearchBarRecord
from aether_vnext.volatility_percentile import (
    RV14_REQUIRED_CLOSES,
    VOLATILITY_PERCENTILE_WINDOW,
    VolatilityPercentileSnapshot,
    empirical_midrank_percentile,
)


@dataclass(frozen=True, slots=True)
class ResearchFeatureBar:
    research_bar_id: str
    asset_id: str
    interval: timedelta
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_at_utc: datetime
    source_id: str

    def __post_init__(self) -> None:
        if self.interval <= timedelta(0):
            raise ValueError("research feature interval must be positive")
        if self.bucket_open_utc.tzinfo is None:
            raise ValueError("bucket_open_utc must be timezone-aware")
        if self.bucket_close_utc.tzinfo is None:
            raise ValueError("bucket_close_utc must be timezone-aware")
        if self.available_at_utc.tzinfo is None:
            raise ValueError("available_at_utc must be timezone-aware")
        if self.bucket_close_utc <= self.bucket_open_utc:
            raise ValueError("research feature bar must be completed")
        if self.available_at_utc < self.bucket_close_utc:
            raise ValueError(
                "research feature bar cannot be available before close"
            )


@dataclass(frozen=True, slots=True)
class ResearchClosedBarFeatureSnapshot:
    asset_id: str
    interval: timedelta
    as_of_utc: datetime
    bar_count: int
    trigger_bar: ResearchFeatureBar
    close: float
    ema20_current: float
    ema20_previous: float
    ema50_current: float
    atr14_current: float
    realized_vol14_current: float
    prior_range: PriorClosedBarRange | None
    indicator_convention_version: str = INDICATOR_CONVENTION_VERSION


@dataclass(frozen=True, slots=True)
class ResearchRegimeReadyFeatures:
    numerical: ResearchClosedBarFeatureSnapshot
    volatility: VolatilityPercentileSnapshot
    volatility_band: VolatilityBand

    def __post_init__(self) -> None:
        if self.numerical.asset_id != self.volatility.asset_id:
            raise ValueError("research regime feature asset mismatch")
        if self.numerical.interval != self.volatility.interval:
            raise ValueError("research regime feature interval mismatch")
        if (
            self.numerical.trigger_bar.bucket_close_utc
            != self.volatility.trigger_close_utc
        ):
            raise ValueError("research regime feature trigger mismatch")
        if (
            abs(
                self.numerical.realized_vol14_current
                - self.volatility.current_realized_vol14
            )
            > 1e-15
        ):
            raise ValueError("research RV14 calculations disagree")
        expected_band = volatility_band(self.volatility.percentile)
        if self.volatility_band is not expected_band:
            raise ValueError(
                "research volatility band disagrees with percentile"
            )


def _feature_bar(row: ResearchBarRecord) -> ResearchFeatureBar:
    return ResearchFeatureBar(
        research_bar_id=row.research_bar_id,
        asset_id=row.asset_id,
        interval=timedelta(seconds=row.interval_seconds),
        bucket_open_utc=row.bucket_open_utc,
        bucket_close_utc=row.bucket_close_utc,
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        volume=float(row.volume),
        available_at_utc=row.available_at_utc,
        source_id=row.source_id,
    )


def _validated_rows(
    selection: PITResearchBarSlice,
) -> tuple[ResearchFeatureBar, ...]:
    rows = tuple(_feature_bar(row) for row in selection.rows)
    if len(rows) < 50:
        raise ValueError(
            "at least 50 PIT research bars are required for replay features"
        )

    interval = timedelta(seconds=selection.interval_seconds)
    prior_open: datetime | None = None
    prior_close: datetime | None = None
    for row in rows:
        if row.asset_id != selection.asset_id:
            raise ValueError("research bar asset does not match PIT selection")
        if row.interval != interval:
            raise ValueError("research bar interval does not match PIT selection")
        if row.bucket_close_utc > selection.as_of_utc:
            raise ValueError("future research bar cannot enter replay features")
        if row.available_at_utc > selection.as_of_utc:
            raise ValueError(
                "unavailable research bar cannot enter replay features"
            )
        if prior_open is not None and row.bucket_open_utc <= prior_open:
            raise ValueError("research bars must be strictly ordered")
        if prior_close is not None and row.bucket_close_utc <= prior_close:
            raise ValueError("research bar closes must be strictly ordered")
        prior_open = row.bucket_open_utc
        prior_close = row.bucket_close_utc
    return rows


def _research_volatility_percentile(
    rows: tuple[ResearchFeatureBar, ...],
) -> VolatilityPercentileSnapshot:
    current_rv = realized_vol14(rows)
    trigger = rows[-1]
    trigger_close = trigger.bucket_close_utc
    window_start = trigger_close - VOLATILITY_PERCENTILE_WINDOW

    pre_window = tuple(
        row
        for row in rows[:-1]
        if row.bucket_close_utc <= window_start
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


def build_research_regime_ready_features(
    selection: PITResearchBarSlice,
    *,
    prior_range_lookback: int | None = None,
) -> ResearchRegimeReadyFeatures:
    """Build no-lookahead replay features from immutable PIT research bars."""
    rows = _validated_rows(selection)

    prior_range: PriorClosedBarRange | None = None
    if prior_range_lookback is not None:
        if (
            not isinstance(prior_range_lookback, int)
            or isinstance(prior_range_lookback, bool)
            or prior_range_lookback <= 0
        ):
            raise ValueError(
                "prior_range_lookback must be a positive integer"
            )
        lookback = prior_range_lookback
        prior_range = prior_closed_bar_range(
            rows,
            lookback_bars=lookback,
        )

    trigger = rows[-1]
    numerical = ResearchClosedBarFeatureSnapshot(
        asset_id=trigger.asset_id,
        interval=trigger.interval,
        as_of_utc=selection.as_of_utc,
        bar_count=len(rows),
        trigger_bar=trigger,
        close=float(trigger.close),
        ema20_current=ema20(rows),
        ema20_previous=ema20(rows[:-1]),
        ema50_current=ema50(rows),
        atr14_current=atr14(rows),
        realized_vol14_current=realized_vol14(rows),
        prior_range=prior_range,
    )
    volatility = _research_volatility_percentile(rows)
    return ResearchRegimeReadyFeatures(
        numerical=numerical,
        volatility=volatility,
        volatility_band=volatility_band(volatility.percentile),
    )
