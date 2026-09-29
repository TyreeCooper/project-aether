from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.full_swap_plan import FullSwapActivationPlan
from aether_vnext.full_swap_rollback import (
    FullSwapRollbackPlan,
    build_full_swap_rollback_plan,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 30, tzinfo=UTC)


def _activation_plan() -> FullSwapActivationPlan:
    return FullSwapActivationPlan(
        readiness_assessment_id="phase17-ready",
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


def test_rollback_plan_starts_offline_and_requires_reconciliation() -> None:
    plan = build_full_swap_rollback_plan(
        _activation_plan(),
        requested_at_utc=T0,
        trigger_reason="runtime_reconciliation_failure",
    )

    assert plan.restore_previous_paper_runtime is True
    assert plan.start_state == "OFFLINE"
    assert plan.reconciliation_required_before_arm is True
    assert plan.automatic_rearm_allowed is False
    assert plan.operator_confirmation_required is True
    assert plan.paper_only is True
    assert plan.live_blocked is True
    assert plan.live_execution_authorized is False
    assert plan.rollback_side_effect_performed is False


def test_rollback_contract_forbids_automatic_rearm() -> None:
    with pytest.raises(ValueError, match="automatic re-arm is forbidden"):
        FullSwapRollbackPlan(
            readiness_assessment_id="phase17-ready",
            requested_at_utc=T0,
            trigger_reason="desync",
            restore_previous_paper_runtime=True,
            start_state="OFFLINE",
            reconciliation_required_before_arm=True,
            automatic_rearm_allowed=True,
            operator_confirmation_required=True,
            paper_only=True,
            live_blocked=True,
            live_execution_authorized=False,
            rollback_side_effect_performed=False,
        )


def test_rollback_contract_cannot_skip_offline_recovery() -> None:
    with pytest.raises(ValueError, match="must start OFFLINE"):
        FullSwapRollbackPlan(
            readiness_assessment_id="phase17-ready",
            requested_at_utc=T0,
            trigger_reason="desync",
            restore_previous_paper_runtime=True,
            start_state="ARMED",
            reconciliation_required_before_arm=True,
            automatic_rearm_allowed=False,
            operator_confirmation_required=True,
            paper_only=True,
            live_blocked=True,
            live_execution_authorized=False,
            rollback_side_effect_performed=False,
        )


def test_rollback_plan_is_descriptive_only() -> None:
    plan = build_full_swap_rollback_plan(
        _activation_plan(),
        requested_at_utc=T0,
        trigger_reason="operator_requested_rollback",
    )

    assert plan.rollback_side_effect_performed is False
    assert plan.live_execution_authorized is False
