from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_features import PriorClosedBarRange
from aether_vnext.bars import Bar
from aether_vnext.playbooks import PlaybookFamily, playbook
from aether_vnext.playbook_runtime import volatility_band
from aether_vnext.replay_cycle import (
    ReplayClosedBarInput,
    ReplayFamilyARequest,
    ReplayFamilyBRequest,
    ReplayFamilyCRequest,
    evaluate_replay_closed_bar,
)
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
)
from aether_vnext.replay_features import (
    ClosedBarFeatureSnapshot,
    RegimeReadyReplayFeatures,
)
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)


def _features(
    *,
    asset_id: str,
    interval: timedelta,
    close: float,
    percentile: float,
    prior_low: float,
    prior_high: float,
    ema20: float,
    ema20_previous: float,
    ema50: float,
) -> RegimeReadyReplayFeatures:
    opened = T0
    closed = opened + interval
    trigger = Bar(
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
    ref_open = opened - interval
    reference = Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=ref_open,
        bucket_close_utc=opened,
        open=(prior_low + prior_high) / 2.0,
        high=prior_high,
        low=prior_low,
        close=(prior_low + prior_high) / 2.0,
        volume=1.0,
        first_exchange_ts=ref_open + timedelta(seconds=1),
        last_exchange_ts=opened - timedelta(microseconds=1),
        print_count=1,
        source_id="reviewed-pit-bars",
    )
    prior = PriorClosedBarRange(
        asset_id=asset_id,
        lookback_bars=20,
        high=prior_high,
        low=prior_low,
        mid=(prior_high + prior_low) / 2.0,
        first_bar=reference,
        last_bar=reference,
    )
    numerical = ClosedBarFeatureSnapshot(
        asset_id=asset_id,
        interval=interval,
        as_of_utc=closed,
        bar_count=100,
        trigger_bar=trigger,
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
        less_count=min(int(percentile), 100),
        equal_count=0,
        percentile=percentile,
    )
    return RegimeReadyReplayFeatures(
        numerical=numerical,
        volatility=volatility,
        volatility_band=volatility_band(percentile),
    )


def _fx_midvol() -> RegimeReadyReplayFeatures:
    spec = playbook("pb_fx_intraday_v1_2")
    return _features(
        asset_id="eurusd",
        interval=spec.trigger_interval,
        close=1.1010,
        percentile=50.0,
        prior_low=1.0980,
        prior_high=1.1000,
        ema20=1.1005,
        ema20_previous=1.1000,
        ema50=1.0990,
    )


def test_replay_cycle_delegates_family_a_precedence() -> None:
    features = _fx_midvol()
    out = evaluate_replay_closed_bar(
        ReplayClosedBarInput(
            asset_id="eurusd",
            horizon="intraday",
            features=features,
            family_a=(
                ReplayFamilyARequest(
                    playbook_id="pb_fx_intraday_v1_2",
                    side="long",
                    extras=FamilyAReplayExtras(
                        slope_ema20_current=1.1005,
                        slope_ema20_previous=1.1000,
                    ),
                ),
            ),
            family_b=(
                ReplayFamilyBRequest(
                    playbook_id="pb_fx_failed_session_v1_3",
                    side="long",
                    state=FamilyBReplayState(
                        break_printed=True,
                        bars_since_break=1,
                        close_back_inside=True,
                        counter_trend_condition=True,
                    ),
                ),
            ),
        )
    )

    assert out.decision.selected_family is PlaybookFamily.A
    assert [row.playbook_id for row in out.decision.watch_candidates] == [
        "pb_fx_intraday_v1_2"
    ]
    assert out.trigger_bar_close_utc == features.numerical.trigger_bar.bucket_close_utc


def test_replay_cycle_selects_family_b_when_a_is_false() -> None:
    spec = playbook("pb_idx_intraday_v1_2")
    features = _features(
        asset_id="mes",
        interval=spec.trigger_interval,
        close=99.0,
        percentile=50.0,
        prior_low=98.0,
        prior_high=100.0,
        ema20=99.0,
        ema20_previous=99.0,
        ema50=100.0,
    )
    out = evaluate_replay_closed_bar(
        ReplayClosedBarInput(
            asset_id="mes",
            horizon="intraday",
            features=features,
            family_a=(
                ReplayFamilyARequest(
                    playbook_id="pb_idx_intraday_v1_2",
                    side="long",
                    extras=FamilyAReplayExtras(
                        trend_ema20=99.0,
                        trend_ema50=100.0,
                    ),
                ),
            ),
            family_b=(
                ReplayFamilyBRequest(
                    playbook_id="pb_idx_failed_v1_3",
                    side="long",
                    state=FamilyBReplayState(
                        break_printed=True,
                        bars_since_break=1,
                        close_back_inside=True,
                        counter_trend_condition=True,
                    ),
                ),
            ),
        )
    )
    assert out.decision.selected_family is PlaybookFamily.B


def test_replay_cycle_can_select_family_c_only_after_a_and_b_fail() -> None:
    spec = playbook("pb_fx_range_v1_3")
    features = _features(
        asset_id="eurusd",
        interval=spec.trigger_interval,
        close=1.0970,
        percentile=20.0,
        prior_low=1.0980,
        prior_high=1.1000,
        ema20=1.0990,
        ema20_previous=1.0990,
        ema50=1.1000,
    )
    out = evaluate_replay_closed_bar(
        ReplayClosedBarInput(
            asset_id="eurusd",
            horizon="intraday",
            features=features,
            family_c=(
                ReplayFamilyCRequest(
                    playbook_id="pb_fx_range_v1_3",
                    side="long",
                    extras=FamilyCReplayExtras(
                        slope_ema20_current=1.0990,
                        slope_ema20_previous=1.0990,
                    ),
                ),
            ),
        )
    )
    assert out.decision.selected_family is PlaybookFamily.C


def test_replay_cycle_does_not_invent_family_b_state() -> None:
    features = _fx_midvol()
    with pytest.raises(ValueError, match="Family-B replay state is required"):
        evaluate_replay_closed_bar(
            ReplayClosedBarInput(
                asset_id="eurusd",
                horizon="intraday",
                features=features,
                family_b=(
                    ReplayFamilyBRequest(
                        playbook_id="pb_fx_failed_session_v1_3",
                        side="long",
                    ),
                ),
            )
        )


def test_replay_cycle_rejects_duplicate_requests() -> None:
    features = _fx_midvol()
    req = ReplayFamilyARequest(
        playbook_id="pb_fx_intraday_v1_2",
        side="long",
        extras=FamilyAReplayExtras(),
    )
    with pytest.raises(ValueError, match="duplicate Family-A"):
        ReplayClosedBarInput(
            asset_id="eurusd",
            horizon="intraday",
            features=features,
            family_a=(req, req),
        )


def test_replay_cycle_preserves_explicit_family_c_dependency() -> None:
    spec = playbook("pb_eq_range_v1_3")
    features = _features(
        asset_id="nvda",
        interval=spec.trigger_interval,
        close=98.0,
        percentile=20.0,
        prior_low=99.0,
        prior_high=100.0,
        ema20=100.0,
        ema20_previous=100.0,
        ema50=101.0,
    )
    with pytest.raises(ValueError, match="trend_not_confirming"):
        evaluate_replay_closed_bar(
            ReplayClosedBarInput(
                asset_id="nvda",
                horizon=spec.horizon,
                features=features,
                family_c=(
                    ReplayFamilyCRequest(
                        playbook_id=spec.playbook_id,
                        side="long",
                    ),
                ),
            )
        )

    out = evaluate_replay_closed_bar(
        ReplayClosedBarInput(
            asset_id="nvda",
            horizon=spec.horizon,
            features=features,
            family_c=(
                ReplayFamilyCRequest(
                    playbook_id=spec.playbook_id,
                    side="long",
                    extras=FamilyCReplayExtras(trend_not_confirming=True),
                ),
            ),
        )
    )
    assert out.decision.selected_family is PlaybookFamily.C
