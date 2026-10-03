"""Rollback/recovery contract for AETHER Phase 17 Full Swap-Out.

This module defines a safe rollback plan only. It does not switch runtime authority,
restart a trading engine, clear desync state, or authorize live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.full_swap_plan import FullSwapActivationPlan


@dataclass(frozen=True, slots=True)
class FullSwapRollbackPlan:
    readiness_assessment_id: str
    requested_at_utc: datetime
    trigger_reason: str
    restore_previous_paper_runtime: bool
    start_state: str
    reconciliation_required_before_arm: bool
    automatic_rearm_allowed: bool
    operator_confirmation_required: bool
    paper_only: bool
    live_blocked: bool
    live_execution_authorized: bool
    rollback_side_effect_performed: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trigger_reason, str)
            or not self.trigger_reason
            or self.trigger_reason != self.trigger_reason.strip()
        ):
            raise ValueError("trigger_reason must be canonical text")
        if self.requested_at_utc.tzinfo is None:
            raise ValueError("requested_at_utc must be timezone-aware")
        if self.restore_previous_paper_runtime is not True:
            raise ValueError("rollback must restore the previous paper runtime")
        if self.start_state != "OFFLINE":
            raise ValueError("rollback recovery must start OFFLINE")
        if self.reconciliation_required_before_arm is not True:
            raise ValueError("rollback requires reconciliation before arm")
        if self.automatic_rearm_allowed is not False:
            raise ValueError("automatic re-arm is forbidden after rollback")
        if self.operator_confirmation_required is not True:
            raise ValueError("rollback re-arm requires operator confirmation")
        if self.paper_only is not True or self.live_blocked is not True:
            raise ValueError("rollback must remain PAPER ONLY / LIVE BLOCKED")
        if self.live_execution_authorized is not False:
            raise ValueError("rollback cannot authorize live execution")
        if self.rollback_side_effect_performed is not False:
            raise ValueError("rollback plan cannot perform runtime side effects")


def build_full_swap_rollback_plan(
    activation_plan: FullSwapActivationPlan,
    *,
    requested_at_utc: datetime,
    trigger_reason: str,
) -> FullSwapRollbackPlan:
    """Build an OFFLINE, reconciliation-first rollback plan."""
    if activation_plan.canonical_runtime != "aether_vnext":
        raise ValueError("rollback source must be canonical aether_vnext runtime")
    if activation_plan.legacy_runtime_code_retained_for_rollback is not True:
        raise ValueError("rollback code is not retained")
    if activation_plan.paper_only is not True or activation_plan.live_blocked is not True:
        raise ValueError("activation plan safety boundary is invalid")

    return FullSwapRollbackPlan(
        readiness_assessment_id=activation_plan.readiness_assessment_id,
        requested_at_utc=requested_at_utc,
        trigger_reason=trigger_reason,
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
