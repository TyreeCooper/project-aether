from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_features import PriorClosedBarRange
from aether_vnext.playbook_runtime import volatility_band
from aether_vnext.playbook_trend_features import (
    PlaybookTrendFeatureSnapshot,
)
from aether_vnext.playbook_trend_requirements import TrendRuleKind
from aether_vnext.playbooks import PlaybookFamily, playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
)
from aether_vnext.research_replay_cycle import (
    ResearchClosedBarInput,
    ResearchFamilyARequest,
    ResearchFamilyBRequest,
    ResearchFamilyCRequest,
    evaluate_research_closed_bar,
)
from aether_vnext.research_replay_features import (
    ResearchClosedBarFeatureSnapshot,
    ResearchFeatureBar,
    ResearchRegimeReadyFeatures,
)
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)


def _bar(
    *,
    research_bar_id: str,
    asset_id: str,
    interval: timedelta,
    opened: datetime,
    close: float,
) -> ResearchFeatureBar:
    closed = opened + interval
    return ResearchFeatureBar(
        research_bar_id=research_bar_id,
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        available_at_utc=closed,
        source_id="reviewed-history",
    )


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
) -> ResearchRegimeReadyFeatures:
    trigger = _bar(
        research_bar_id="trigger-bar",
        asset_id=asset_id,
        interval=interval,
        opened=T0,
        close=close,
    )
    first_ref = _bar(
        research_bar_id="ref-1",
        asset_id=asset_id,
        interval=interval,
        opened=T0 - (2 * interval),
        close=(prior_low + prior_high) / 2.0,
    )
    last_ref = _bar(
        research_bar_id="ref-2",
        asset_id=asset_id,
        interval=interval,
        opened=T0 - interval,
        close=(prior_low + prior_high) / 2.0,
    )
    prior = PriorClosedBarRange(
        asset_id=asset_id,
        lookback_bars=20,
        high=prior_high,
        low=prior_low,
        mid=(prior_high + prior_low) / 2.0,
        first_bar=first_ref,
        last_bar=last_ref,
    )
    numerical = ResearchClosedBarFeatureSnapshot(
        asset_id=asset_id,
        interval=interval,
        as_of_utc=trigger.bucket_close_utc,
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
        trigger_close_utc=trigger.bucket_close_utc,
        window_start_utc=trigger.bucket_close_utc - timedelta(days=90),
        window_end_exclusive_utc=trigger.bucket_close_utc,
        current_realized_vol14=0.1,
        reference_count=100,
        less_count=min(int(percentile), 100),
        equal_count=0,
        percentile=percentile,
    )
    return ResearchRegimeReadyFeatures(
        numerical=numerical,
        volatility=volatility,
        volatility_band=volatility_band(percentile),
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("asset_id", " EURUSD ", "asset_id must be a canonical lowercase ID"),
        ("asset_id", "EURUSD", "asset_id must be a canonical lowercase ID"),
        ("asset_id", 1, "asset_id must be a canonical lowercase ID"),
        ("horizon", " intraday ", "horizon must be canonical text"),
        ("horizon", 1, "horizon must be canonical text"),
    ),
)
def test_research_cycle_requires_canonical_identity(
    field: str,
    value: object,
    message: str,
) -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
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
    kwargs = {
        "asset_id": "eurusd",
        "horizon": spec.horizon,
        "features": features,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        ResearchClosedBarInput(**kwargs)


def test_research_cycle_applies_family_a_without_live_bar_fields() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
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

    out = evaluate_research_closed_bar(
        ResearchClosedBarInput(
            asset_id="eurusd",
            horizon=spec.horizon,
            features=features,
            family_a=(
                ResearchFamilyARequest(
                    playbook_id=spec.playbook_id,
                    side="long",
                    extras=FamilyAReplayExtras(
                        slope_ema20_current=1.1005,
                        slope_ema20_previous=1.1000,
                    ),
                ),
            ),
        )
    )

    assert out.decision.selected_family is PlaybookFamily.A
    assert out.trigger_research_bar_id == "trigger-bar"
    assert not hasattr(features.numerical.trigger_bar, "last_exchange_ts")


def test_research_cycle_applies_family_b_with_explicit_pit_state() -> None:
    spec = playbook("pb_idx_failed_v1_3")
    features = _features(
        asset_id="mes",
        interval=spec.trigger_interval,
        close=99.0,
        percentile=50.0,
        prior_low=90.0,
        prior_high=100.0,
        ema20=99.0,
        ema20_previous=99.0,
        ema50=100.0,
    )

    out = evaluate_research_closed_bar(
        ResearchClosedBarInput(
            asset_id="mes",
            horizon=spec.horizon,
            features=features,
            family_b=(
                ResearchFamilyBRequest(
                    playbook_id=spec.playbook_id,
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


def test_research_cycle_applies_family_c_after_a_and_b_are_absent() -> None:
    spec = playbook("pb_fx_range_v1_3")
    features = _features(
        asset_id="eurusd",
        interval=spec.trigger_interval,
        close=0.99,
        percentile=20.0,
        prior_low=1.00,
        prior_high=1.02,
        ema20=1.01,
        ema20_previous=1.01,
        ema50=1.02,
    )

    out = evaluate_research_closed_bar(
        ResearchClosedBarInput(
            asset_id="eurusd",
            horizon=spec.horizon,
            features=features,
            family_c=(
                ResearchFamilyCRequest(
                    playbook_id=spec.playbook_id,
                    side="long",
                    extras=FamilyCReplayExtras(
                        slope_ema20_current=1.01,
                        slope_ema20_previous=1.01,
                    ),
                ),
            ),
        )
    )
    assert out.decision.selected_family is PlaybookFamily.C


def test_research_cycle_rejects_duplicate_route_requests() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
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
    request = ResearchFamilyARequest(
        playbook_id=spec.playbook_id,
        side="long",
        extras=FamilyAReplayExtras(
            slope_ema20_current=1.1005,
            slope_ema20_previous=1.1000,
        ),
    )

    with pytest.raises(ValueError, match="duplicate Family-A"):
        ResearchClosedBarInput(
            asset_id="eurusd",
            horizon=spec.horizon,
            features=features,
            family_a=(request, request),
        )



def test_research_cycle_accepts_reviewed_trend_snapshot_directly() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
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
    trigger_close = features.numerical.trigger_bar.bucket_close_utc
    trend = PlaybookTrendFeatureSnapshot(
        playbook_id=spec.playbook_id,
        asset_id="eurusd",
        interval=timedelta(hours=1),
        as_of_utc=trigger_close,
        source_bar_count=60,
        last_bar_close_utc=trigger_close - timedelta(minutes=15),
        rule_kind=TrendRuleKind.EMA20_SLOPE,
        ema20_current=1.1005,
        ema20_previous=1.1000,
        ema50_current=None,
    )

    out = evaluate_research_closed_bar(
        ResearchClosedBarInput(
            asset_id="eurusd",
            horizon=spec.horizon,
            features=features,
            family_a=(
                ResearchFamilyARequest(
                    playbook_id=spec.playbook_id,
                    side="long",
                    trend=trend,
                ),
            ),
        )
    )
    assert out.decision.selected_family is PlaybookFamily.A


def test_research_cycle_rejects_manual_trend_override_when_snapshot_present() -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    features = _features(
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
    trigger_close = features.numerical.trigger_bar.bucket_close_utc
    trend = PlaybookTrendFeatureSnapshot(
        playbook_id=spec.playbook_id,
        asset_id="eurusd",
        interval=timedelta(hours=1),
        as_of_utc=trigger_close,
        source_bar_count=60,
        last_bar_close_utc=trigger_close - timedelta(minutes=15),
        rule_kind=TrendRuleKind.EMA20_SLOPE,
        ema20_current=1.1005,
        ema20_previous=1.1000,
        ema50_current=None,
    )

    with pytest.raises(ValueError, match="cannot be combined"):
        ResearchFamilyARequest(
            playbook_id=spec.playbook_id,
            side="long",
            trend=trend,
            extras=FamilyAReplayExtras(
                slope_ema20_current=1.1005,
                slope_ema20_previous=1.1000,
            ),
        )
