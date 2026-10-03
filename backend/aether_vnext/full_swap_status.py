"""Read-only operator projection for AETHER Phase 17 Full Swap-Out."""
from __future__ import annotations

from aether_vnext.full_swap_plan import FullSwapActivationPlan
from aether_vnext.full_swap_readiness import FullSwapReadinessAssessment
from aether_vnext.full_swap_rollback import FullSwapRollbackPlan


def build_full_swap_status(
    *,
    readiness: FullSwapReadinessAssessment,
    activation_plan: FullSwapActivationPlan | None = None,
    rollback_plan: FullSwapRollbackPlan | None = None,
) -> dict[str, object]:
    """Project Phase-17 state without changing runtime authority."""
    if activation_plan is not None:
        if activation_plan.readiness_assessment_id != readiness.assessment_id:
            raise ValueError("activation plan/readiness identity mismatch")
        if readiness.swap_ready is not True:
            raise ValueError("activation plan cannot coexist with blocked readiness")

    if rollback_plan is not None:
        if activation_plan is None:
            raise ValueError("rollback plan requires an activation plan")
        if rollback_plan.readiness_assessment_id != readiness.assessment_id:
            raise ValueError("rollback plan/readiness identity mismatch")

    checks = {name: value for name, value in readiness.checks}
    return {
        "phase": 17,
        "phase_name": "Full Swap-Out",
        "assessment_id": readiness.assessment_id,
        "assessed_at_utc": readiness.assessed_at_utc.isoformat(),
        "swap_ready": readiness.swap_ready,
        "blocking_reasons": list(readiness.blocking_reasons),
        "checks": checks,
        "activation_plan_present": activation_plan is not None,
        "rollback_plan_present": rollback_plan is not None,
        "planned_canonical_runtime": (
            None
            if activation_plan is None
            else activation_plan.canonical_runtime
        ),
        "runtime_authority_changed": False,
        "legacy_runtime_authority_retired_actual": False,
        "live_execution_authorized": False,
        "authority": {
            "read_only": True,
            "may_switch_runtime": False,
            "may_start_runtime": False,
            "may_arm_runtime": False,
            "may_enable_live": False,
        },
    }
