"""Provider-neutral closed-bar runtime-cycle contract for AETHER vNext.

This module deliberately does not calculate indicators, read providers, mutate the
Firm book, size Risk, or execute orders. It binds one already-completed trigger bar
to already-evaluated Family A/B/C predicates and applies the existing deterministic
A -> B -> C precedence engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.bars import Bar
from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.family_b import FamilyBEvaluation
from aether_vnext.family_c import FamilyCEvaluation
from aether_vnext.playbook_engine import (
    ClosedBarRuntimeDecision,
    resolve_closed_bar_runtime,
)


@dataclass(frozen=True, slots=True)
class ClosedBarCycleInput:
    asset_id: str
    horizon: str
    trigger_bar: Bar
    family_a: tuple[FamilyAEvaluation, ...] = ()
    family_b: tuple[FamilyBEvaluation, ...] = ()
    family_c: tuple[FamilyCEvaluation, ...] = ()

    def __post_init__(self) -> None:
        asset = str(self.asset_id).strip().lower()
        if not asset:
            raise ValueError("asset_id is required")
        if not str(self.horizon).strip():
            raise ValueError("horizon is required")
        if self.trigger_bar.asset_id != asset:
            raise ValueError("trigger_bar asset_id mismatch")
        if self.trigger_bar.bucket_open_utc.tzinfo is None:
            raise ValueError("trigger_bar bucket_open_utc must be timezone-aware")
        if self.trigger_bar.bucket_close_utc.tzinfo is None:
            raise ValueError("trigger_bar bucket_close_utc must be timezone-aware")
        if self.trigger_bar.bucket_close_utc <= self.trigger_bar.bucket_open_utc:
            raise ValueError("trigger_bar must be closed")
        if self.trigger_bar.last_exchange_ts >= self.trigger_bar.bucket_close_utc:
            raise ValueError(
                "trigger_bar last_exchange_ts must precede bucket close"
            )


@dataclass(frozen=True, slots=True)
class ClosedBarCycleResult:
    asset_id: str
    horizon: str
    trigger_bar_open_utc: datetime
    trigger_bar_close_utc: datetime
    decision: ClosedBarRuntimeDecision


def evaluate_closed_bar_cycle(
    cycle: ClosedBarCycleInput,
) -> ClosedBarCycleResult:
    decision = resolve_closed_bar_runtime(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        family_a=cycle.family_a,
        family_b=cycle.family_b,
        family_c=cycle.family_c,
    )
    return ClosedBarCycleResult(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        trigger_bar_open_utc=cycle.trigger_bar.bucket_open_utc,
        trigger_bar_close_utc=cycle.trigger_bar.bucket_close_utc,
        decision=decision,
    )
