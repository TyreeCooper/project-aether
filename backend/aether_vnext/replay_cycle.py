"""Deterministic closed-bar replay-cycle orchestration for AETHER vNext.

This module composes already-bound replay features and Family A/B/C replay adapters,
then delegates same-bar precedence to the existing runtime_cycle/playbook_engine.

It does not calculate provider data, choose unresolved lookbacks, create Setup/Ticket
records, apply costs/Risk/Governor, simulate fills, or persist evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.bars import Bar
from aether_vnext.playbooks import playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
    evaluate_replay_family_a,
    evaluate_replay_family_b,
    evaluate_replay_family_c,
)
from aether_vnext.replay_failed_break import (
    FrozenBreakReference,
    reconstruct_family_b_state,
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
class ReplayFamilyBEpisode:
    bars: tuple[Bar, ...]
    reference: FrozenBreakReference
    break_bar_close_utc: datetime
    counter_trend_condition: bool
    position_key_open: bool = False
    locate_ok: bool | None = None


@dataclass(frozen=True, slots=True)
class ReplayFamilyBRequest:
    playbook_id: str
    side: str
    state: FamilyBReplayState | None = None
    episode: ReplayFamilyBEpisode | None = None

    def __post_init__(self) -> None:
        if (self.state is None) == (self.episode is None):
            raise ValueError(
                "Family-B replay request requires exactly one of state or episode"
            )


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
        spec = playbook(row.playbook_id)
        state = row.state
        if state is None:
            episode = row.episode
            if episode is None:
                raise ValueError(
                    f"Family-B replay episode is required for {row.playbook_id}"
                )
            state = reconstruct_family_b_state(
                spec,
                asset_id=cycle.asset_id,
                side=row.side,
                bars=episode.bars,
                reference=episode.reference,
                break_bar_close_utc=episode.break_bar_close_utc,
                counter_trend_condition=episode.counter_trend_condition,
                position_key_open=episode.position_key_open,
                locate_ok=episode.locate_ok,
            )
        b_rows.append(
            evaluate_replay_family_b(
                spec,
                asset_id=cycle.asset_id,
                side=row.side,
                features=cycle.features,
                state=state,
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
