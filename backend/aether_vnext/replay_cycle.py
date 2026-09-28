"""Deterministic closed-bar replay-cycle orchestration for AETHER vNext.

This module composes already-bound replay features and Family A/B/C replay adapters,
then delegates same-bar precedence to the existing runtime_cycle/playbook_engine.

It does not calculate provider data, choose unresolved lookbacks, create Setup/Ticket
records, apply costs/Risk/Governor, simulate fills, or persist evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.playbooks import playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
    evaluate_replay_family_a,
    evaluate_replay_family_b,
    evaluate_replay_family_c,
)
from aether_vnext.replay_features import RegimeReadyReplayFeatures
from aether_vnext.runtime_cycle import (
    ClosedBarCycleInput,
    ClosedBarCycleResult,
    evaluate_closed_bar_cycle,
)


@dataclass(frozen=True, slots=True)
class ReplayFamilyARequest:
    playbook_id: str
    side: str
    extras: FamilyAReplayExtras | None = None


@dataclass(frozen=True, slots=True)
class ReplayFamilyBRequest:
    playbook_id: str
    side: str
    state: FamilyBReplayState | None = None


@dataclass(frozen=True, slots=True)
class ReplayFamilyCRequest:
    playbook_id: str
    side: str
    extras: FamilyCReplayExtras | None = None


@dataclass(frozen=True, slots=True)
class ReplayClosedBarInput:
    asset_id: str
    horizon: str
    features: RegimeReadyReplayFeatures
    family_a: tuple[ReplayFamilyARequest, ...] = ()
    family_b: tuple[ReplayFamilyBRequest, ...] = ()
    family_c: tuple[ReplayFamilyCRequest, ...] = ()

    def __post_init__(self) -> None:
        asset = str(self.asset_id).strip().lower()
        if not asset:
            raise ValueError("asset_id is required")
        if not str(self.horizon).strip():
            raise ValueError("horizon is required")
        if self.features.numerical.asset_id != asset:
            raise ValueError("replay cycle feature asset mismatch")
        _reject_duplicates(self.family_a, label="Family-A")
        _reject_duplicates(self.family_b, label="Family-B")
        _reject_duplicates(self.family_c, label="Family-C")


def _reject_duplicates(rows: tuple[object, ...], *, label: str) -> None:
    keys: set[tuple[str, str]] = set()
    for row in rows:
        playbook_id = str(getattr(row, "playbook_id"))
        side = str(getattr(row, "side"))
        key = (playbook_id, side)
        if key in keys:
            raise ValueError(f"duplicate {label} replay request: {key}")
        keys.add(key)


def evaluate_replay_closed_bar(
    cycle: ReplayClosedBarInput,
) -> ClosedBarCycleResult:
    """Evaluate one PIT closed-bar cycle through the frozen family precedence."""
    a = tuple(
        evaluate_replay_family_a(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            extras=row.extras,
        )
        for row in cycle.family_a
    )

    b_rows = []
    for row in cycle.family_b:
        if row.state is None:
            raise ValueError(
                f"Family-B replay state is required for {row.playbook_id}"
            )
        b_rows.append(
            evaluate_replay_family_b(
                playbook(row.playbook_id),
                asset_id=cycle.asset_id,
                side=row.side,
                features=cycle.features,
                state=row.state,
            )
        )

    c = tuple(
        evaluate_replay_family_c(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            extras=row.extras,
        )
        for row in cycle.family_c
    )

    return evaluate_closed_bar_cycle(
        ClosedBarCycleInput(
            asset_id=cycle.asset_id,
            horizon=cycle.horizon,
            trigger_bar=cycle.features.numerical.trigger_bar,
            family_a=a,
            family_b=tuple(b_rows),
            family_c=c,
        )
    )
