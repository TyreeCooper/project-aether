from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.shadow_cutover_telemetry import (
    FUNNEL_STAGES,
    PriorPolicyShadowObservation,
    build_shadow_cutover_telemetry,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 20, 0, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    aggregate_id: str,
    seat: str,
    minute: int,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "aggregate_id": aggregate_id,
        "seat": seat,
        "created_at_utc": T0 + timedelta(minutes=minute),
    }


def test_shadow_telemetry_tracks_canonical_funnel_first_killers_and_dwell() -> None:
    events = (
        _event("e1", aggregate_id="candidate-1", seat="Scout", minute=-7),
        _event("e2", aggregate_id="candidate-1", seat="Sniper", minute=-6),
        _event("e3", aggregate_id="candidate-1", seat="Risk", minute=-5),
        _event("e4", aggregate_id="candidate-1", seat="Clerk", minute=-4),
        _event("e5", aggregate_id="candidate-1", seat="Portfolio", minute=-3),
        _event("e6", aggregate_id="candidate-1", seat="Floor", minute=-2),
        _event("e7", aggregate_id="candidate-2", seat="Scout", minute=-1),
    )
    lineage = (
        {
            "first_killed_by": "Risk",
            "first_kill_reason": "portfolio_risk_limit",
        },
        {
            "first_killed_by": "Risk",
            "first_kill_reason": "portfolio_risk_limit",
        },
        {
            "first_killed_by": "Clerk",
            "first_kill_reason": "invalid_market",
        },
    )

    result = build_shadow_cutover_telemetry(
        as_of_utc=T0,
        universe_count=12,
        event_rows=events,
        decision_lineage_rows=lineage,
    )

    assert tuple(result["traffic_funnel"]) == FUNNEL_STAGES
    assert result["traffic_funnel"] == {
        "UNIVERSE": 12,
        "WATCH": 2,
        "FIRE": 1,
        "SIZE": 1,
        "READY": 1,
        "ORDER": 1,
        "OPEN": 1,
    }
    assert result["first_killer_distribution"] == [
        {"seat": "Clerk", "reason": "invalid_market", "count": 1},
        {"seat": "Risk", "reason": "portfolio_risk_limit", "count": 2},
    ]
    first = result["dwell_time"][0]
    assert first["aggregate_id"] == "candidate-1"
    assert first["stage"] == "WATCH"
    assert first["dwell_seconds"] == 60.0
    assert result["authority"]["may_create_orders"] is False


def test_prior_policy_shadow_records_counterfactual_without_order_authority() -> None:
    observations = (
        PriorPolicyShadowObservation(
            observation_id="shadow-pass",
            candidate_ref="candidate-1",
            route_id="btc:1h:long",
            prior_policy_version="policy-v0",
            current_policy_version="policy-v1",
            observed_at_utc=T0,
            would_have_passed_prior_policy=True,
        ),
        PriorPolicyShadowObservation(
            observation_id="shadow-block",
            candidate_ref="candidate-2",
            route_id="eth:1h:long",
            prior_policy_version="policy-v0",
            current_policy_version="policy-v1",
            observed_at_utc=T0,
            would_have_passed_prior_policy=False,
            prior_policy_blocker="legacy_cost_hurdle",
        ),
        PriorPolicyShadowObservation(
            observation_id="shadow-unknown",
            candidate_ref="candidate-3",
            route_id="mes:intraday:long",
            prior_policy_version="policy-v0",
            current_policy_version="policy-v1",
            observed_at_utc=T0,
            would_have_passed_prior_policy=None,
        ),
    )

    result = build_shadow_cutover_telemetry(
        as_of_utc=T0,
        universe_count=12,
        event_rows=(),
        decision_lineage_rows=(),
        prior_policy_observations=observations,
    )

    summary = result["prior_policy_shadow"]
    assert summary["observation_count"] == 3
    assert summary["would_have_passed"] == 1
    assert summary["would_have_blocked"] == 1
    assert summary["unknown"] == 1
    assert all(row["order_created"] is False for row in summary["records"])
    assert all(
        row["trade_influence_enabled"] is False
        for row in summary["records"]
    )


def test_shadow_comparison_cannot_create_order_or_enable_trade_influence() -> None:
    with pytest.raises(ValueError, match="cannot create an order"):
        PriorPolicyShadowObservation(
            observation_id="bad-order",
            candidate_ref="candidate-1",
            route_id="btc:1h:long",
            prior_policy_version="policy-v0",
            current_policy_version="policy-v1",
            observed_at_utc=T0,
            would_have_passed_prior_policy=True,
            order_created=True,
        )

    with pytest.raises(ValueError, match="cannot influence trading"):
        PriorPolicyShadowObservation(
            observation_id="bad-influence",
            candidate_ref="candidate-1",
            route_id="btc:1h:long",
            prior_policy_version="policy-v0",
            current_policy_version="policy-v1",
            observed_at_utc=T0,
            would_have_passed_prior_policy=True,
            trade_influence_enabled=True,
        )


def test_shadow_telemetry_rejects_future_information() -> None:
    with pytest.raises(ValueError, match="future event"):
        build_shadow_cutover_telemetry(
            as_of_utc=T0,
            universe_count=12,
            event_rows=(
                _event(
                    "future",
                    aggregate_id="candidate-1",
                    seat="Scout",
                    minute=1,
                ),
            ),
            decision_lineage_rows=(),
        )
