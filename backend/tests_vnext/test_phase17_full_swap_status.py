from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.full_swap_plan import FullSwapActivationPlan
from aether_vnext.full_swap_readiness import FullSwapReadinessAssessment
from aether_vnext.full_swap_rollback import FullSwapRollbackPlan
from aether_vnext.full_swap_status import build_full_swap_status


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 45, tzinfo=UTC)


def _readiness(*, ready: bool) -> FullSwapReadinessAssessment:
    return FullSwapReadinessAssessment(
        assessment_id="phase17-status",
        assessed_at_utc=T0,
        swap_ready=ready,
        live_execution_authorized=False,
        blocking_reasons=(
            () if ready else ("phase16_runtime_shadow_verified",)
        ),
        checks=(
            ("phase16_runtime_shadow_verified", ready),
            ("paper_only", True),
            ("live_blocked", True),
        ),
    )


def _activation() -> FullSwapActivationPlan:
    return FullSwapActivationPlan(
        readiness_assessment_id="phase17-status",
        canonical_runtime="aether_vnext",
        legacy_runtime_authority_retired=True,
        legacy_runtime_code_retained_for_rollback=True,
        reconciliation_required_before_arm=True,
        restart_state="OFFLINE",
        paper_only=True,
        live_blocked=True,
        live_execution_authorized=False,
        activation_side_effect_performed=False,
    )


def _rollback() -> FullSwapRollbackPlan:
    return FullSwapRollbackPlan(
        readiness_assessment_id="phase17-status",
        requested_at_utc=T0,
        trigger_reason="runtime_reconciliation_failure",
        restore_previous_paper_runtime=True,
        start_state="OFFLINE",
        reconciliation_required_before_arm=True,
        automatic_rearm_allowed=False,
        operator_confirmation_required=True,
        paper_only=True,
        live_blocked=True,
        live_execution_authorized=False,
        rollback_side_effect_performed=False,
    )


def test_blocked_status_surfaces_runtime_shadow_gate_without_side_effect() -> None:
    result = build_full_swap_status(readiness=_readiness(ready=False))

    assert result["swap_ready"] is False
    assert result["blocking_reasons"] == ["phase16_runtime_shadow_verified"]
    assert result["runtime_authority_changed"] is False
    assert result["legacy_runtime_authority_retired_actual"] is False
    assert result["authority"]["may_switch_runtime"] is False
    assert result["live_execution_authorized"] is False


def test_planned_status_distinguishes_plan_from_actual_authority_change() -> None:
    result = build_full_swap_status(
        readiness=_readiness(ready=True),
        activation_plan=_activation(),
    )

    assert result["swap_ready"] is True
    assert result["activation_plan_present"] is True
    assert result["planned_canonical_runtime"] == "aether_vnext"
    assert result["runtime_authority_changed"] is False
    assert result["legacy_runtime_authority_retired_actual"] is False


def test_status_can_show_prebuilt_rollback_without_performing_it() -> None:
    result = build_full_swap_status(
        readiness=_readiness(ready=True),
        activation_plan=_activation(),
        rollback_plan=_rollback(),
    )

    assert result["rollback_plan_present"] is True
    assert result["runtime_authority_changed"] is False
    assert result["authority"]["may_start_runtime"] is False


def test_blocked_readiness_cannot_be_paired_with_activation_plan() -> None:
    with pytest.raises(ValueError, match="blocked readiness"):
        build_full_swap_status(
            readiness=_readiness(ready=False),
            activation_plan=_activation(),
        )
