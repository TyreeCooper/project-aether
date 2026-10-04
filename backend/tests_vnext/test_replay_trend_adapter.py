from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bars import Bar
from aether_vnext.playbook_runtime import volatility_band
from aether_vnext.playbook_trend_features import (
    PlaybookTrendFeatureSnapshot,
)
from aether_vnext.playbook_trend_requirements import TrendRuleKind
from aether_vnext.playbooks import playbook
from aether_vnext.replay_features import (
    ClosedBarFeatureSnapshot,
    RegimeReadyReplayFeatures,
)
from aether_vnext.replay_trend_adapter import (
    family_a_extras_from_trend_snapshot,
)
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)


def _features(
    *,
    asset_id: str,
    interval: timedelta,
) -> RegimeReadyReplayFeatures:
    opened = T0
    closed = opened + interval
    bar = Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=closed - timedelta(microseconds=1),
        print_count=1,
        source_id="reviewed-pit-bars",
    )
    numerical = ClosedBarFeatureSnapshot(
        asset_id=asset_id,
        interval=interval,
        as_of_utc=closed,
        bar_count=100,
        trigger_bar=bar,
        close=100.5,
        ema20_current=100.0,
        ema20_previous=99.0,
        ema50_current=98.0,
        atr14_current=1.0,
        realized_vol14_current=0.1,
        prior_range=None,
    )
    volatility = VolatilityPercentileSnapshot(
        asset_id=asset_id,
        interval=interval,
        trigger_close_utc=closed,
        window_start_utc=closed - timedelta(days=90),
        window_end_exclusive_utc=closed,
        current_realized_vol14=0.1,
        reference_count=100,
        less_count=50,
        equal_count=0,
        percentile=50.0,
    )
    return RegimeReadyReplayFeatures(
        numerical=numerical,
        volatility=volatility,
        volatility_band=volatility_band(50.0),
    )


def _trend(
    *,
    playbook_id: str,
    asset_id: str,
    interval: timedelta,
    rule: TrendRuleKind,
    trigger_close: datetime,
    ema20: float = 110.0,
    ema20_previous: float | None = None,
    ema50: float | None = None,
    as_of_offset: timedelta = timedelta(0),
    last_close_offset: timedelta = timedelta(0),
) -> PlaybookTrendFeatureSnapshot:
    return PlaybookTrendFeatureSnapshot(
        playbook_id=playbook_id,
        asset_id=asset_id,
        interval=interval,
        as_of_utc=trigger_close + as_of_offset,
        source_bar_count=60,
        last_bar_close_utc=trigger_close + last_close_offset,
        rule_kind=rule,
        ema20_current=ema20,
        ema20_previous=ema20_previous,
        ema50_current=ema50,
    )


def test_fx_intraday_maps_one_hour_slope_into_family_a_extras() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
        asset_id="eurusd",
        interval=spec.trigger_interval,
    )
    trigger_close = features.numerical.trigger_bar.bucket_close_utc
    trend = _trend(
        playbook_id=spec.playbook_id,
        asset_id="eurusd",
        interval=timedelta(hours=1),
        rule=TrendRuleKind.EMA20_SLOPE,
        trigger_close=trigger_close,
        ema20=101.0,
        ema20_previous=100.0,
    )

    extras = family_a_extras_from_trend_snapshot(
        spec,
        asset_id="eurusd",
        features=features,
        trend=trend,
    )

    assert extras.slope_ema20_current == pytest.approx(101.0)
    assert extras.slope_ema20_previous == pytest.approx(100.0)
    assert extras.trend_ema20 is None
    assert extras.trend_ema50 is None


def test_crypto_swing_maps_daily_level_pair_and_keeps_btc_dependency_explicit() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    features = _features(
        asset_id="btc",
        interval=spec.trigger_interval,
    )
    trigger_close = features.numerical.trigger_bar.bucket_close_utc
    trend = _trend(
        playbook_id=spec.playbook_id,
        asset_id="btc",
        interval=timedelta(days=1),
        rule=TrendRuleKind.EMA20_EMA50_LEVEL,
        trigger_close=trigger_close,
        ema20=110.0,
        ema50=100.0,
    )

    extras = family_a_extras_from_trend_snapshot(
        spec,
        asset_id="btc",
        features=features,
        trend=trend,
        btc_daily_close=105.0,
        btc_daily_ema50=100.0,
    )

    assert extras.trend_ema20 == pytest.approx(110.0)
    assert extras.trend_ema50 == pytest.approx(100.0)
    assert extras.slope_ema20_current is None
    assert extras.btc_daily_close == pytest.approx(105.0)
    assert extras.btc_daily_ema50 == pytest.approx(100.0)


def test_adapter_refuses_playbook_asset_or_interval_drift() -> None:
    spec = playbook("pb_eq_intraday_v1_2")
    features = _features(
        asset_id="nvda",
        interval=spec.trigger_interval,
    )
    trigger_close = features.numerical.trigger_bar.bucket_close_utc

    with pytest.raises(ValueError, match="playbook mismatch"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="nvda",
            features=features,
            trend=_trend(
                playbook_id="pb_eq_swing_v1_2",
                asset_id="nvda",
                interval=timedelta(minutes=15),
                rule=TrendRuleKind.EMA20_EMA50_LEVEL,
                trigger_close=trigger_close,
                ema50=100.0,
            ),
        )

    with pytest.raises(ValueError, match="asset mismatch"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="nvda",
            features=features,
            trend=_trend(
                playbook_id=spec.playbook_id,
                asset_id="tsla",
                interval=timedelta(minutes=15),
                rule=TrendRuleKind.EMA20_EMA50_LEVEL,
                trigger_close=trigger_close,
                ema50=100.0,
            ),
        )

    with pytest.raises(ValueError, match="interval mismatch"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="nvda",
            features=features,
            trend=_trend(
                playbook_id=spec.playbook_id,
                asset_id="nvda",
                interval=timedelta(hours=1),
                rule=TrendRuleKind.EMA20_EMA50_LEVEL,
                trigger_close=trigger_close,
                ema50=100.0,
            ),
        )


def test_future_trend_state_fails_closed() -> None:
    spec = playbook("pb_idx_intraday_v1_2")
    features = _features(
        asset_id="mes",
        interval=spec.trigger_interval,
    )
    trigger_close = features.numerical.trigger_bar.bucket_close_utc

    with pytest.raises(ValueError, match="future trend bar"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="mes",
            features=features,
            trend=_trend(
                playbook_id=spec.playbook_id,
                asset_id="mes",
                interval=timedelta(minutes=15),
                rule=TrendRuleKind.EMA20_EMA50_LEVEL,
                trigger_close=trigger_close,
                ema50=100.0,
                last_close_offset=timedelta(seconds=1),
            ),
        )

    with pytest.raises(ValueError, match="future trend snapshot"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="mes",
            features=features,
            trend=_trend(
                playbook_id=spec.playbook_id,
                asset_id="mes",
                interval=timedelta(minutes=15),
                rule=TrendRuleKind.EMA20_EMA50_LEVEL,
                trigger_close=trigger_close,
                ema50=100.0,
                as_of_offset=timedelta(seconds=1),
            ),
        )


def test_rule_shape_mismatch_fails_closed() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
        asset_id="eurusd",
        interval=spec.trigger_interval,
    )
    trigger_close = features.numerical.trigger_bar.bucket_close_utc

    with pytest.raises(ValueError, match="requires previous EMA20"):
        family_a_extras_from_trend_snapshot(
            spec,
            asset_id="eurusd",
            features=features,
            trend=_trend(
                playbook_id=spec.playbook_id,
                asset_id="eurusd",
                interval=timedelta(hours=1),
                rule=TrendRuleKind.EMA20_SLOPE,
                trigger_close=trigger_close,
                ema20_previous=None,
            ),
        )
