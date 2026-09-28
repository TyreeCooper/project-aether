from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_features import PriorClosedBarRange
from aether_vnext.bars import Bar
from aether_vnext.playbook_runtime import VolatilityBand
from aether_vnext.playbooks import playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
    evaluate_replay_family_a,
    evaluate_replay_family_b,
    evaluate_replay_family_c,
)
from aether_vnext.replay_features import (
    ClosedBarFeatureSnapshot,
    RegimeReadyReplayFeatures,
)
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


def _features(
    *,
    asset_id: str,
    interval: timedelta,
    close: float,
    percentile: float,
    prior_low: float | None = 99.0,
    prior_high: float | None = 100.0,
    ema20: float = 110.0,
    ema20_previous: float = 109.0,
    ema50: float = 100.0,
) -> RegimeReadyReplayFeatures:
    opened = T0
    closed = opened + interval
    bar = Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1.0,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=closed - timedelta(microseconds=1),
        print_count=1,
        source_id="reviewed-pit-bars",
    )
    prior = (
        None
        if prior_low is None or prior_high is None
        else PriorClosedBarRange(
            lookback_bars=20,
            high=prior_high,
            low=prior_low,
        )
    )
    numerical = ClosedBarFeatureSnapshot(
        asset_id=asset_id,
        interval=interval,
        as_of_utc=closed,
        bar_count=100,
        trigger_bar=bar,
        close=close,
        ema20_current=ema20,
        ema20_previous=ema20_previous,
        ema50_current=ema50,
        atr14_current=1.0,
        realized_vol14_current=0.1,
        prior_range=prior,
    )
    volatility = VolatilityPercentileSnapshot(
        asset_id=asset_id,
        interval=interval,
        trigger_close_utc=closed,
        window_start_utc=closed - timedelta(days=90),
        window_end_exclusive_utc=closed,
        current_realized_vol14=0.1,
        reference_count=100,
        less_count=int(percentile),
        equal_count=0,
        percentile=percentile,
    )
    band = (
        VolatilityBand.BELOW_40
        if percentile < 40
        else VolatilityBand.ABOVE_85
        if percentile > 85
        else VolatilityBand.BETWEEN_40_85
    )
    return RegimeReadyReplayFeatures(
        numerical=numerical,
        volatility=volatility,
        volatility_band=band,
    )


def test_family_a_replay_uses_bound_features_and_explicit_daily_dependency() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    features = _features(
        asset_id="btc",
        interval=timedelta(hours=1),
        close=101.0,
        percentile=50.0,
    )
    out = evaluate_replay_family_a(
        spec,
        asset_id="btc",
        side="long",
        features=features,
        extras=FamilyAReplayExtras(
            btc_daily_close=105.0,
            btc_daily_ema50=100.0,
        ),
    )
    assert out.watch_eligible is True


def test_family_a_replay_does_not_invent_missing_cross_timeframe_dependency() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    features = _features(
        asset_id="btc",
        interval=timedelta(hours=1),
        close=101.0,
        percentile=50.0,
    )
    with pytest.raises(ValueError, match="btc_daily_close"):
        evaluate_replay_family_a(
            spec,
            asset_id="btc",
            side="long",
            features=features,
        )


def test_family_b_replay_keeps_event_state_explicit() -> None:
    spec = playbook("pb_idx_failed_v1_3")
    features = _features(
        asset_id="mes",
        interval=timedelta(minutes=15),
        close=99.0,
        percentile=50.0,
    )
    out = evaluate_replay_family_b(
        spec,
        asset_id="mes",
        side="long",
        features=features,
        state=FamilyBReplayState(
            break_printed=True,
            bars_since_break=1,
            close_back_inside=True,
            counter_trend_condition=True,
        ),
    )
    assert out.watch_eligible is True


def test_family_c_replay_uses_explicit_playbook_correct_prior_range() -> None:
    spec = playbook("pb_fx_range_v1_3")
    features = _features(
        asset_id="eurusd",
        interval=timedelta(minutes=15),
        close=98.0,
        percentile=20.0,
        ema20=100.0,
        ema20_previous=100.0,
    )
    out = evaluate_replay_family_c(
        spec,
        asset_id="eurusd",
        side="long",
        features=features,
    )
    assert out.watch_eligible is True


def test_family_c_equity_nonconfirmation_is_not_invented() -> None:
    spec = playbook("pb_eq_range_v1_3")
    features = _features(
        asset_id="nvda",
        interval=timedelta(minutes=1),
        close=98.0,
        percentile=20.0,
    )
    with pytest.raises(ValueError, match="trend_not_confirming"):
        evaluate_replay_family_c(
            spec,
            asset_id="nvda",
            side="long",
            features=features,
        )

    out = evaluate_replay_family_c(
        spec,
        asset_id="nvda",
        side="long",
        features=features,
        extras=FamilyCReplayExtras(trend_not_confirming=True),
    )
    assert out.watch_eligible is True


def test_adapter_refuses_wrong_trigger_interval() -> None:
    spec = playbook("pb_eq_intraday_v1_2")
    features = _features(
        asset_id="nvda",
        interval=timedelta(hours=1),
        close=101.0,
        percentile=50.0,
    )
    with pytest.raises(ValueError, match="trigger interval"):
        evaluate_replay_family_a(
            spec,
            asset_id="nvda",
            side="long",
            features=features,
        )
