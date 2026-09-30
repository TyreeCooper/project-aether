from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.prototype_crypto_entry_plan import (
    PROTOTYPE_COST_EDGE_MULTIPLE,
    build_prototype_crypto_entry_plan,
    prototype_entry_ids,
)
from aether_vnext.prototype_crypto_features import PrototypeCryptoFeatureSnapshot
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)


def _feature(*, eligible: bool = True) -> PrototypeCryptoFeatureSnapshot:
    vol = VolatilityPercentileSnapshot(
        asset_id="btc",
        interval=timedelta(hours=1),
        trigger_close_utc=T0,
        window_start_utc=T0 - timedelta(days=90),
        window_end_exclusive_utc=T0,
        current_realized_vol14=0.01,
        reference_count=2160,
        less_count=1296,
        equal_count=0,
        percentile=60.0,
    )
    family = FamilyAEvaluation(
        playbook_id="pb_crypto_swing_v1_2",
        asset_id="btc",
        side="long",
        definition_enabled=True,
        regime_eligible=True,
        structure_rule=eligible,
        dependency_ok=True,
    )
    return PrototypeCryptoFeatureSnapshot(
        asset_id="btc",
        trigger_close_utc=T0,
        close=101_500.0,
        atr14=1_000.0,
        prior_20h_high=101_000.0,
        prior_20h_low=95_000.0,
        daily_ema20=100_000.0,
        daily_ema50=98_000.0,
        btc_daily_close=101_000.0,
        btc_daily_ema50=98_000.0,
        volatility=vol,
        family_a=family,
    )


def _observation(*, bid: float = 101_480.0, ask: float = 101_500.0) -> MarketObservation:
    mark = (bid + ask) / 2.0
    spread = ask - bid
    return MarketObservation(
        observation_id="obs-prototype-plan",
        asset_id="btc",
        venue="kraken",
        bid=bid,
        ask=ask,
        last=mark,
        mark=mark,
        source="kraken_public",
        exchange_ts=T0 + timedelta(seconds=1),
        received_ts=T0 + timedelta(seconds=1),
        age_ms=0,
        spread_abs=spread,
        spread_bps=(spread / mark) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="test",
    )


def test_eligible_crypto_plan_binds_stop_target_and_exit_contract() -> None:
    plan = build_prototype_crypto_entry_plan(
        feature=_feature(),
        current_observation=_observation(),
        as_of_utc=T0 + timedelta(seconds=2),
    )
    assert plan.eligible is True
    assert plan.reason == "family_a_watch"
    assert plan.hard_stop_price == 94_800.0
    assert plan.first_target_price is not None
    assert plan.exit_plan is not None
    assert plan.exit_plan.trailing_policy.enabled is False
    assert plan.exit_plan.profit_take_policy.enabled is False
    assert plan.exit_plan.governor_halt_behavior == "flatten"
    assert plan.estimated_cost_per_unit is not None
    assert plan.estimated_cost_per_unit.cost_edge_multiple == PROTOTYPE_COST_EDGE_MULTIPLE
    assert PROTOTYPE_COST_EDGE_MULTIPLE == 1.40


def test_structure_fail_plan_is_read_only_no_entry_contract() -> None:
    plan = build_prototype_crypto_entry_plan(
        feature=_feature(eligible=False),
        current_observation=_observation(),
        as_of_utc=T0 + timedelta(seconds=2),
    )
    assert plan.eligible is False
    assert plan.reason == "structure_fail"
    assert plan.geometry is None
    assert plan.exit_plan is None
    assert plan.estimated_cost_per_unit is None


def test_intrabar_quote_dip_does_not_fake_completed_bar_invalidation() -> None:
    plan = build_prototype_crypto_entry_plan(
        feature=_feature(),
        current_observation=_observation(bid=100_900.0, ask=100_920.0),
        as_of_utc=T0 + timedelta(seconds=2),
    )
    assert plan.eligible is True
    # Source-bound invalidation is a future completed 1h close below the frozen
    # breakout level, not a current-bid touch/dip.
    assert plan.invalidation_hit is False


def test_entry_ids_are_deterministic_per_closed_bar() -> None:
    left = prototype_entry_ids(asset_id="btc", trigger_close_utc=T0)
    right = prototype_entry_ids(asset_id="btc", trigger_close_utc=T0)
    later = prototype_entry_ids(
        asset_id="btc",
        trigger_close_utc=T0 + timedelta(hours=1),
    )
    assert left == right
    assert left.setup_id != later.setup_id
    assert left.event_id("risk") == right.event_id("risk")
