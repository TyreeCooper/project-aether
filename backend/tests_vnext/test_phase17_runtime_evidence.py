from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.full_swap_runtime_evidence import (
    RestartScenarioEvidence,
    RollbackRuntimeEvidence,
    RuntimeShadowEvidence,
    assess_phase17_runtime_evidence,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 30, tzinfo=UTC)
REV = "deadbeef" * 5


def _shadow(**overrides) -> RuntimeShadowEvidence:
    values = {
        "evidence_id": "shadow-1",
        "environment": "aether-vnext-burnin",
        "deployed_revision": REV,
        "observed_at_utc": T0,
        "floor_route_status_code": 200,
        "dedicated_vnext_book_read": True,
        "legacy_surface_available": True,
        "mutation_transport_absent": True,
        "second_runtime_started": False,
        "paper_only": True,
        "live_blocked": True,
        "source_artifact_ids": ("workflow-run-1", "floor-response-1"),
        "synthetic": False,
    }
    values.update(overrides)
    return RuntimeShadowEvidence(**values)


def _restart(scenario: str, **overrides) -> RestartScenarioEvidence:
    values = {
        "scenario_id": f"restart-{scenario}",
        "scenario": scenario,
        "deployed_revision": REV,
        "observed_at_utc": T0,
        "identity_preserved": True,
        "cash_preserved": True,
        "margin_preserved": True,
        "position_state_preserved": True,
        "idempotency_preserved": True,
        "reconciliation_clean": True,
        "source_artifact_ids": (f"artifact-{scenario}",),
        "synthetic": False,
    }
    values.update(overrides)
    return RestartScenarioEvidence(**values)


def _rollback(**overrides) -> RollbackRuntimeEvidence:
    values = {
        "evidence_id": "rollback-1",
        "deployed_revision": REV,
        "observed_at_utc": T0,
        "previous_paper_runtime_restored": True,
        "recovery_started_offline": True,
        "reconciliation_clean_before_arm": True,
        "automatic_rearm_observed": False,
        "operator_confirmation_required": True,
        "paper_only": True,
        "live_blocked": True,
        "source_artifact_ids": ("rollback-run-1",),
        "synthetic": False,
    }
    values.update(overrides)
    return RollbackRuntimeEvidence(**values)


def test_complete_one_revision_runtime_evidence_is_accepted() -> None:
    result = assess_phase17_runtime_evidence(
        shadow=_shadow(),
        restart_scenarios=(
            _restart("mid_ticket"),
            _restart("mid_order"),
            _restart("open_trade"),
        ),
        rollback=_rollback(),
    )

    assert result.runtime_shadow_verified is True
    assert result.restart_recovery_verified is True
    assert result.rollback_verified is True
    assert result.activation_evidence_complete is True
    assert result.blocking_reasons == ()


def test_missing_restart_scenario_keeps_activation_blocked() -> None:
    result = assess_phase17_runtime_evidence(
        shadow=_shadow(),
        restart_scenarios=(
            _restart("mid_ticket"),
            _restart("open_trade"),
        ),
        rollback=_rollback(),
    )

    assert result.restart_recovery_verified is False
    assert result.activation_evidence_complete is False
    assert result.blocking_reasons == ("restart_recovery_not_verified",)


def test_runtime_shadow_failure_and_rollback_failure_are_independent() -> None:
    result = assess_phase17_runtime_evidence(
        shadow=_shadow(legacy_surface_available=False),
        restart_scenarios=(
            _restart("mid_ticket"),
            _restart("mid_order"),
            _restart("open_trade"),
        ),
        rollback=_rollback(automatic_rearm_observed=True),
    )

    assert result.activation_evidence_complete is False
    assert result.blocking_reasons == (
        "phase16_runtime_shadow_not_verified",
        "rollback_not_verified",
    )


def test_synthetic_evidence_is_rejected_at_contract_boundary() -> None:
    with pytest.raises(ValueError, match="synthetic runtime-shadow evidence"):
        _shadow(synthetic=True)

    with pytest.raises(ValueError, match="synthetic restart evidence"):
        _restart("mid_order", synthetic=True)

    with pytest.raises(ValueError, match="synthetic rollback evidence"):
        _rollback(synthetic=True)


def test_runtime_evidence_must_share_one_deployed_revision() -> None:
    with pytest.raises(ValueError, match="share one deployed revision"):
        assess_phase17_runtime_evidence(
            shadow=_shadow(),
            restart_scenarios=(
                _restart("mid_ticket"),
                _restart("mid_order"),
                _restart("open_trade", deployed_revision="different"),
            ),
            rollback=_rollback(),
        )
