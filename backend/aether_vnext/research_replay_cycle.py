"""Research-only closed-bar replay orchestration for AETHER vNext.

This module evaluates immutable PIT research features through the frozen Family A/B/C
evaluators and the existing deterministic same-bar precedence engine.

It deliberately bypasses runtime_cycle because immutable research bars do not and
must not fabricate live exchange-print timestamps. No Setup/Ticket, Risk, fill,
database, or campaign mutation occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.family_b import FamilyBEvaluation
from aether_vnext.family_c import FamilyCEvaluation
from aether_vnext.playbook_engine import (
    ClosedBarRuntimeDecision,
    resolve_closed_bar_runtime,
)
from aether_vnext.playbooks import playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
    evaluate_replay_family_a,
    evaluate_replay_family_b,
    evaluate_replay_family_c,
)
from aether_vnext.research_replay_features import (
    ResearchRegimeReadyFeatures,
)


@dataclass(frozen=True, slots=True)
class ResearchFamilyARequest:
    playbook_id: str
    side: str
    extras: FamilyAReplayExtras | None = None


@dataclass(frozen=True, slots=True)
class ResearchFamilyBRequest:
    playbook_id: str
    side: str
    state: FamilyBReplayState


@dataclass(frozen=True, slots=True)
class ResearchFamilyCRequest:
    playbook_id: str
    side: str
    extras: FamilyCReplayExtras | None = None


@dataclass(frozen=True, slots=True)
class ResearchClosedBarInput:
    asset_id: str
    horizon: str
    features: ResearchRegimeReadyFeatures
    family_a: tuple[ResearchFamilyARequest, ...] = ()
    family_b: tuple[ResearchFamilyBRequest, ...] = ()
    family_c: tuple[ResearchFamilyCRequest, ...] = ()

    def __post_init__(self) -> None:
        asset = str(self.asset_id).strip().lower()
        if not asset:
            raise ValueError("asset_id is required")
        if not str(self.horizon).strip():
            raise ValueError("horizon is required")
        if self.features.numerical.asset_id != asset:
            raise ValueError("research feature asset mismatch")
        _reject_duplicates(self.family_a, "Family-A")
        _reject_duplicates(self.family_b, "Family-B")
        _reject_duplicates(self.family_c, "Family-C")


@dataclass(frozen=True, slots=True)
class ResearchClosedBarResult:
    asset_id: str
    horizon: str
    trigger_research_bar_id: str
    trigger_bar_open_utc: datetime
    trigger_bar_close_utc: datetime
    decision: ClosedBarRuntimeDecision


def _reject_duplicates(rows: tuple[object, ...], label: str) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (
            str(getattr(row, "playbook_id")),
            str(getattr(row, "side")),
        )
        if key in seen:
            raise ValueError(f"duplicate {label} research replay request: {key}")
        seen.add(key)


def evaluate_research_closed_bar(
    cycle: ResearchClosedBarInput,
) -> ResearchClosedBarResult:
    """Evaluate one immutable PIT research trigger through A -> B -> C precedence."""
    a: tuple[FamilyAEvaluation, ...] = tuple(
        evaluate_replay_family_a(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            extras=row.extras,
        )
        for row in cycle.family_a
    )
    b: tuple[FamilyBEvaluation, ...] = tuple(
        evaluate_replay_family_b(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            state=row.state,
        )
        for row in cycle.family_b
    )
    c: tuple[FamilyCEvaluation, ...] = tuple(
        evaluate_replay_family_c(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            extras=row.extras,
        )
        for row in cycle.family_c
    )

    decision = resolve_closed_bar_runtime(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        family_a=a,
        family_b=b,
        family_c=c,
    )
    trigger = cycle.features.numerical.trigger_bar
    return ResearchClosedBarResult(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        trigger_research_bar_id=trigger.research_bar_id,
        trigger_bar_open_utc=trigger.bucket_open_utc,
        trigger_bar_close_utc=trigger.bucket_close_utc,
        decision=decision,
    )
