from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.research_bar_selection import PITResearchBarSlice
from aether_vnext.playbook_runtime import VolatilityBand
from aether_vnext.research_replay_features import (
    ResearchClosedBarFeatureSnapshot,
    ResearchFeatureBar,
    ResearchRegimeReadyFeatures,
    build_research_regime_ready_features,
)
from aether_vnext.research_warehouse import ResearchBarRecord


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def _row(
    index: int,
    *,
    close: float = 100.0,
    available_offset: timedelta = timedelta(0),
) -> ResearchBarRecord:
    opened = T0 + index * DAY
    closed = opened + DAY
    return ResearchBarRecord(
        research_bar_id=f"bar-{index}",
        dataset_snapshot_id="dataset-1",
        asset_id="btc",
        interval_seconds=86_400,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        source_id="reviewed-history",
        source_data_version="v1",
        source_ref="reviewed-ref",
        available_at_utc=closed + available_offset,
    )


def _selection(
    *,
    count: int = 110,
    trigger_close: float = 110.0,
) -> PITResearchBarSlice:
    rows = tuple(_row(i) for i in range(count - 1)) + (
        _row(count - 1, close=trigger_close),
    )
    return PITResearchBarSlice(
        dataset_snapshot_id="dataset-1",
        asset_id="btc",
        interval_seconds=86_400,
        as_of_utc=rows[-1].bucket_close_utc,
        start_at_utc=None,
        rows=rows,
    )


def _feature_bar_from_row(
    row: ResearchBarRecord,
    *,
    asset_id: str | None = None,
    interval: timedelta | None = None,
) -> ResearchFeatureBar:
    return ResearchFeatureBar(
        research_bar_id=row.research_bar_id,
        asset_id=row.asset_id if asset_id is None else asset_id,
        interval=(
            timedelta(seconds=row.interval_seconds)
            if interval is None
            else interval
        ),
        bucket_open_utc=row.bucket_open_utc,
        bucket_close_utc=row.bucket_close_utc,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        available_at_utc=row.available_at_utc,
        source_id=row.source_id,
    )


def test_research_feature_bar_requires_canonical_asset_identity() -> None:
    row = _row(0)
    with pytest.raises(ValueError, match="asset_id must be canonical text"):
        _feature_bar_from_row(row, asset_id=" BTC ")


def test_research_feature_interval_must_match_bucket_duration() -> None:
    row = _row(0)
    with pytest.raises(ValueError, match="interval must match bucket duration"):
        _feature_bar_from_row(row, interval=timedelta(hours=12))


@pytest.mark.parametrize(
    ("field", "value_factory", "message"),
    (
        (
            "asset_id",
            lambda base: "eth",
            "feature snapshot asset mismatch",
        ),
        (
            "interval",
            lambda base: timedelta(hours=12),
            "feature snapshot interval mismatch",
        ),
        (
            "as_of_utc",
            lambda base: base.trigger_bar.bucket_close_utc - timedelta(seconds=1),
            "cannot precede trigger close",
        ),
        (
            "bar_count",
            lambda base: 49,
            "requires at least 50 bars",
        ),
        (
            "close",
            lambda base: base.close + 1.0,
            "close must match trigger",
        ),
        (
            "indicator_convention_version",
            lambda base: "other",
            "indicator convention mismatch",
        ),
    ),
)
def test_research_feature_snapshot_rejects_lineage_drift(
    field: str,
    value_factory: object,
    message: str,
) -> None:
    base = build_research_regime_ready_features(
        _selection(),
        prior_range_lookback=20,
    ).numerical
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value_factory(base)

    with pytest.raises(ValueError, match=message):
        ResearchClosedBarFeatureSnapshot(**kwargs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "open",
            True,
            "prices/volume must be numeric, not boolean",
        ),
        (
            "close",
            float("nan"),
            "prices/volume must be finite",
        ),
        (
            "close",
            0.0,
            "prices must be positive",
        ),
        (
            "volume",
            -1.0,
            "volume cannot be negative",
        ),
        (
            "high",
            50.0,
            "high is inconsistent",
        ),
        (
            "low",
            100.5,
            "low is inconsistent",
        ),
    ),
)
def test_research_feature_bar_rejects_invalid_numerics(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _feature_bar_from_row(_row(0))
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        ResearchFeatureBar(**kwargs)


def test_research_features_use_pit_availability_not_exchange_timestamps() -> None:
    result = build_research_regime_ready_features(
        _selection(),
        prior_range_lookback=20,
    )

    assert result.numerical.asset_id == "btc"
    assert result.numerical.ema20_current > 0.0
    assert result.numerical.ema50_current > 0.0
    assert result.numerical.atr14_current > 0.0
    assert result.numerical.realized_vol14_current > 0.0
    assert result.numerical.prior_range is not None
    assert not hasattr(
        result.numerical.trigger_bar,
        "last_exchange_ts",
    )


def test_research_percentile_excludes_trigger_and_uses_prior_90_days() -> None:
    result = build_research_regime_ready_features(_selection())

    assert result.volatility.reference_count == 90
    assert result.volatility.less_count == 90
    assert result.volatility.equal_count == 0
    assert result.volatility.percentile == pytest.approx(100.0)
    assert result.volatility.current_realized_vol14 == pytest.approx(
        result.numerical.realized_vol14_current
    )


def test_research_regime_band_must_match_percentile() -> None:
    result = build_research_regime_ready_features(_selection())

    with pytest.raises(
        ValueError,
        match="volatility band disagrees with percentile",
    ):
        ResearchRegimeReadyFeatures(
            numerical=result.numerical,
            volatility=result.volatility,
            volatility_band=VolatilityBand.BELOW_40,
        )


def test_prior_range_excludes_trigger_bar() -> None:
    selection = _selection()
    result = build_research_regime_ready_features(
        selection,
        prior_range_lookback=20,
    )
    reference = selection.rows[-21:-1]

    assert result.numerical.prior_range is not None
    assert result.numerical.prior_range.high == pytest.approx(
        max(row.high for row in reference)
    )
    assert result.numerical.prior_range.low == pytest.approx(
        min(row.low for row in reference)
    )


@pytest.mark.parametrize(
    "lookback",
    (20.5, "20", True, 0, -1),
)
def test_prior_range_lookback_requires_exact_positive_integer(
    lookback: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="prior_range_lookback must be a positive integer",
    ):
        build_research_regime_ready_features(
            _selection(),
            prior_range_lookback=lookback,
        )


def test_unavailable_research_bar_fails_closed() -> None:
    selection = _selection()
    rows = list(selection.rows)
    last = rows[-1]
    rows[-1] = ResearchBarRecord(
        research_bar_id=last.research_bar_id,
        dataset_snapshot_id=last.dataset_snapshot_id,
        asset_id=last.asset_id,
        interval_seconds=last.interval_seconds,
        bucket_open_utc=last.bucket_open_utc,
        bucket_close_utc=last.bucket_close_utc,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=last.volume,
        source_id=last.source_id,
        source_data_version=last.source_data_version,
        source_ref=last.source_ref,
        available_at_utc=selection.as_of_utc + timedelta(seconds=1),
    )
    bad = PITResearchBarSlice(
        dataset_snapshot_id=selection.dataset_snapshot_id,
        asset_id=selection.asset_id,
        interval_seconds=selection.interval_seconds,
        as_of_utc=selection.as_of_utc,
        start_at_utc=None,
        rows=tuple(rows),
    )

    with pytest.raises(ValueError, match="unavailable research bar"):
        build_research_regime_ready_features(bad)


def test_full_90_day_reference_requires_pre_window_warmup() -> None:
    selection = _selection(count=91, trigger_close=110.0)
    with pytest.raises(ValueError, match="pre-window RV14 warm-up"):
        build_research_regime_ready_features(selection)
