"""Immutable activation plan for AETHER Phase 17 Full Swap-Out.

The plan is descriptive control-plane state only. Building a plan never switches
runtime authority, starts a trading loop, deploys code, or authorizes live execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.full_swap_readiness import FullSwapReadinessAssessment


@dataclass(frozen=True, slots=True)
class FullSwapActivationPlan:
    readiness_assessment_id: str
    canonical_runtime: str
    legacy_runtime_authority_retired: bool
    legacy_runtime_code_retained_for_rollback: bool
    reconciliation_required_before_arm: bool
    restart_state: str
    paper_only: bool
    live_blocked: bool
    live_execution_authorized: bool
    activation_side_effect_performed: bool

    def __post_init__(self) -> None:
        if self.canonical_runtime != "aether_vnext":
            raise ValueError("canonical runtime must be aether_vnext")
        if self.legacy_runtime_authority_retired is not True:
            raise ValueError("legacy runtime authority must be retired")
        if self.legacy_runtime_code_retained_for_rollback is not True:
            raise ValueError("rollback code must remain available")
        if self.reconciliation_required_before_arm is not True:
            raise ValueError("reconciliation must be required before arm")
        if self.restart_state != "OFFLINE":
            raise ValueError("full-swap restart state must be OFFLINE")
        if self.paper_only is not True or self.live_blocked is not True:
            raise ValueError("Full Swap-Out must remain PAPER ONLY / LIVE BLOCKED")
        if self.live_execution_authorized is not False:
            raise ValueError("Full Swap-Out cannot authorize live execution")
        if self.activation_side_effect_performed is not False:
            raise ValueError("activation plan cannot perform runtime side effects")

    def as_payload(self) -> dict[str, object]:
        return {
            "readiness_assessment_id": self.readiness_assessment_id,
            "canonical_runtime": self.canonical_runtime,
            "legacy_runtime_authority_retired": True,
            "legacy_runtime_code_retained_for_rollback": True,
            "reconciliation_required_before_arm": True,
            "restart_state": "OFFLINE",
            "paper_only": True,
            "live_blocked": True,
            "live_execution_authorized": False,
            "activation_side_effect_performed": False,
        }


def build_full_swap_activation_plan(
    readiness: FullSwapReadinessAssessment,
) -> FullSwapActivationPlan:
    """Build the immutable handoff plan only after every readiness gate is green."""
    if readiness.swap_ready is not True:
        blockers = ",".join(readiness.blocking_reasons) or "unknown"
        raise RuntimeError(
            f"Full Swap-Out activation plan blocked by readiness: {blockers}"
        )
    if readiness.live_execution_authorized is not False:
        raise RuntimeError("readiness cannot authorize live execution")

    return FullSwapActivationPlan(
        readiness_assessment_id=readiness.assessment_id,
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
