from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.event_performance_matrix import (
    MechanismEventPerformanceCell,
    MechanismEventPerformanceKey,
    MechanismEventPerformanceObservation,
    build_mechanism_event_performance_matrix,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 17, 0, tzinfo=UTC)


def _row(
    observation_id: str,
    *,
    pnl: float,
    event_type: str = "scheduled_macro_surprise",
    mechanism_id: str = "trend",
    phase: str = "post_event",
    minute: int = 0,
) -> MechanismEventPerformanceObservation:
    return MechanismEventPerformanceObservation(
        observation_id=observation_id,
        event_id=f"event-{observation_id}",
        event_type=event_type,
        mechanism_id=mechanism_id,
        playbook_id="pb-trend",
        playbook_version="v1",
        route_id="btc:1h:trend",
        asset_id="btc",
        regime_phase=phase,
        regime_id="risk_off",
        net_pnl_usd=pnl,
        observed_at_utc=T0 + timedelta(minutes=minute),
        source_record_ids=(f"trade-{observation_id}", f"event-{observation_id}"),
    )


def test_matrix_aggregates_declared_links_without_causal_claim() -> None:
    result = build_mechanism_event_performance_matrix(
        (
            _row("obs-2", pnl=-20.0, minute=2),
            _row("obs-1", pnl=50.0, minute=1),
            _row("obs-3", pnl=0.0, minute=3),
        )
    )

    assert len(result) == 1
    cell = result[0]
    assert cell.sample_count == 3
    assert cell.win_count == 1
    assert cell.loss_count == 1
    assert cell.flat_count == 1
    assert cell.net_pnl_usd == 30.0
    assert cell.mean_net_pnl_usd == 10.0
    assert cell.observation_ids == ("obs-1", "obs-2", "obs-3")
    assert cell.association_only is True
    assert cell.causal_claim is False
    assert cell.trade_influence_allowed is False
    assert cell.independent_evidence_credit is False


def test_matrix_keeps_mechanism_and_event_regime_phase_separate() -> None:
    result = build_mechanism_event_performance_matrix(
        (
            _row("trend-pre", pnl=5.0, phase="pre_event"),
            _row("trend-post", pnl=8.0, phase="post_event"),
            _row(
                "failed-post",
                pnl=-4.0,
                mechanism_id="failed-break",
                phase="post_event",
            ),
        )
    )

    assert len(result) == 3
    assert {
        (cell.key.mechanism_id, cell.key.regime_phase)
        for cell in result
    } == {
        ("trend", "pre_event"),
        ("trend", "post_event"),
        ("failed-break", "post_event"),
    }


def test_matrix_rejects_duplicate_observation_identity() -> None:
    row = _row("duplicate", pnl=1.0)
    with pytest.raises(ValueError, match="duplicate event-performance observation_id"):
        build_mechanism_event_performance_matrix((row, row))


def test_matrix_boundary_cannot_be_changed_into_causal_or_trade_authority() -> None:
    key = MechanismEventPerformanceKey(
        event_type="scheduled_macro_surprise",
        mechanism_id="trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        route_id="btc:1h:trend",
        asset_id="btc",
        regime_phase="post_event",
        regime_id="risk_off",
    )

    with pytest.raises(ValueError, match="cannot claim causation"):
        MechanismEventPerformanceCell(
            key=key,
            sample_count=1,
            win_count=1,
            loss_count=0,
            flat_count=0,
            net_pnl_usd=1.0,
            mean_net_pnl_usd=1.0,
            observation_ids=("obs-1",),
            source_record_ids=("trade-1", "event-1"),
            causal_claim=True,
        )

    with pytest.raises(ValueError, match="cannot influence trades"):
        MechanismEventPerformanceCell(
            key=key,
            sample_count=1,
            win_count=1,
            loss_count=0,
            flat_count=0,
            net_pnl_usd=1.0,
            mean_net_pnl_usd=1.0,
            observation_ids=("obs-1",),
            source_record_ids=("trade-1", "event-1"),
            trade_influence_allowed=True,
        )
