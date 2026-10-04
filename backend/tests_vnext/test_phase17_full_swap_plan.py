from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.full_swap_plan import (
    FullSwapActivationPlan,
    build_full_swap_activation_plan,
)
from aether_vnext.full_swap_readiness import (
    FullSwapReadinessAssessment,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 15, tzinfo=UTC)


def _assessment(*, ready: bool = True) -> FullSwapReadinessAssessment:
    blockers = () if ready else ("phase16_runtime_shadow_verified",)
    return FullSwapReadinessAssessment(
        assessment_id="phase17-ready",
        assessed_at_utc=T0,
        swap_ready=ready,
        live_execution_authorized=False,
        blocking_reasons=blockers,
        checks=(
            ("phase16_runtime_shadow_verified", ready),
            ("paper_only", True),
            ("live_blocked", True),
        ),
    )


def test_ready_assessment_builds_offline_paper_only_handoff_plan() -> None:
    plan = build_full_swap_activation_plan(_assessment())

    assert plan.canonical_runtime == "aether_vnext"
    assert plan.legacy_runtime_authority_retired is True
    assert plan.legacy_runtime_code_retained_for_rollback is True
    assert plan.reconciliation_required_before_arm is True
    assert plan.restart_state == "OFFLINE"
    assert plan.paper_only is True
    assert plan.live_blocked is True
    assert plan.live_execution_authorized is False
    assert plan.activation_side_effect_performed is False


def test_unresolved_shadow_runtime_evidence_blocks_activation_plan() -> None:
    with pytest.raises(RuntimeError, match="phase16_runtime_shadow_verified"):
        build_full_swap_activation_plan(_assessment(ready=False))


def test_activation_plan_cannot_relax_live_or_recovery_boundaries() -> None:
    with pytest.raises(ValueError, match="PAPER ONLY / LIVE BLOCKED"):
        FullSwapActivationPlan(
            readiness_assessment_id="bad-live",
            canonical_runtime="aether_vnext",
            legacy_runtime_authority_retired=True,
            legacy_runtime_code_retained_for_rollback=True,
            reconciliation_required_before_arm=True,
            restart_state="OFFLINE",
            paper_only=True,
            live_blocked=False,
            live_execution_authorized=False,
            activation_side_effect_performed=False,
        )

    with pytest.raises(ValueError, match="restart state must be OFFLINE"):
        FullSwapActivationPlan(
            readiness_assessment_id="bad-restart",
            canonical_runtime="aether_vnext",
            legacy_runtime_authority_retired=True,
            legacy_runtime_code_retained_for_rollback=True,
            reconciliation_required_before_arm=True,
            restart_state="ARMED",
            paper_only=True,
            live_blocked=True,
            live_execution_authorized=False,
            activation_side_effect_performed=False,
        )


def test_plan_payload_is_descriptive_and_has_no_activation_side_effect() -> None:
    payload = build_full_swap_activation_plan(_assessment()).as_payload()

    assert payload["activation_side_effect_performed"] is False
    assert payload["live_execution_authorized"] is False
    assert payload["reconciliation_required_before_arm"] is True
