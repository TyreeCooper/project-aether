"""Integrated deterministic Playbook Runtime for AETHER vNext Phase 7.

This layer composes already-evaluated Family A/B/C predicates and applies the
binding same-bar precedence. It may identify WATCH-eligible playbook candidates.
It does not create Setup/Ticket records, apply Clerk cost gating, size Risk,
admit Governor state, or execute orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeAlias

from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.family_b import FamilyBEvaluation
from aether_vnext.family_c import FamilyCEvaluation
from aether_vnext.playbook_exits import exit_rule
from aether_vnext.playbooks import PlaybookFamily, playbook


FamilyEvaluation: TypeAlias = (
    FamilyAEvaluation | FamilyBEvaluation | FamilyCEvaluation
)


@dataclass(frozen=True, slots=True)
class RuntimeWatchCandidate:
    playbook_id: str
    family: PlaybookFamily
    asset_id: str
    side: str
    horizon: str
    exit_contract_complete: bool
    exit_contract_gap: str | None


@dataclass(frozen=True, slots=True)
class ClosedBarRuntimeDecision:
    asset_id: str
    horizon: str
    selected_family: PlaybookFamily | None
    reason: str
    family_a_structure_present: bool
    family_b_structure_present: bool
    family_c_structure_present: bool
    watch_candidates: tuple[RuntimeWatchCandidate, ...]
    suppressed_by_precedence: tuple[str, ...]


def _normalize(
    rows: Iterable[FamilyEvaluation],
    *,
    family: PlaybookFamily,
    asset_id: str,
    horizon: str,
) -> tuple[FamilyEvaluation, ...]:
    result: list[FamilyEvaluation] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        spec = playbook(row.playbook_id)
        if spec.family is not family:
            raise ValueError(
                f"{row.playbook_id} is {spec.family}, expected {family}"
            )
        if row.asset_id != asset_id:
            raise ValueError(
                f"evaluation asset mismatch: {row.asset_id} != {asset_id}"
            )
        if spec.horizon != horizon:
            raise ValueError(
                f"evaluation horizon mismatch: {spec.horizon} != {horizon}"
            )
        key = (row.playbook_id, row.side)
        if key in seen:
            raise ValueError(f"duplicate evaluation: {key}")
        seen.add(key)
        result.append(row)
    return tuple(
        sorted(result, key=lambda row: (row.playbook_id, row.side))
    )


def _candidate(row: FamilyEvaluation) -> RuntimeWatchCandidate:
    spec = playbook(row.playbook_id)
    rule = exit_rule(row.playbook_id)
    return RuntimeWatchCandidate(
        playbook_id=row.playbook_id,
        family=spec.family,
        asset_id=row.asset_id,
        side=row.side,
        horizon=spec.horizon,
        exit_contract_complete=rule.source_complete,
        exit_contract_gap=rule.unresolved_reason,
    )


def resolve_closed_bar_runtime(
    *,
    asset_id: str,
    horizon: str,
    family_a: Iterable[FamilyAEvaluation] = (),
    family_b: Iterable[FamilyBEvaluation] = (),
    family_c: Iterable[FamilyCEvaluation] = (),
) -> ClosedBarRuntimeDecision:
    """Apply exact A -> B -> C precedence for one asset:horizon closed bar."""
    if not asset_id:
        raise ValueError("asset_id is required")
    if not horizon:
        raise ValueError("horizon is required")

    a = _normalize(
        family_a,
        family=PlaybookFamily.A,
        asset_id=asset_id,
        horizon=horizon,
    )
    b = _normalize(
        family_b,
        family=PlaybookFamily.B,
        asset_id=asset_id,
        horizon=horizon,
    )
    c = _normalize(
        family_c,
        family=PlaybookFamily.C,
        asset_id=asset_id,
        horizon=horizon,
    )

    a_structure = any(row.structure_rule for row in a)
    b_structure = any(row.structure_rule for row in b)
    c_structure = any(row.structure_rule for row in c)

    if a_structure:
        selected = PlaybookFamily.A
        reason = "family_a_structure_precedence"
        selected_rows: tuple[FamilyEvaluation, ...] = a
        suppressed_rows = (*b, *c)
    elif b_structure:
        selected = PlaybookFamily.B
        reason = "family_b_fail_event_precedence"
        selected_rows = b
        suppressed_rows = c
    elif c_structure:
        selected = PlaybookFamily.C
        reason = "family_c_structure_precedence"
        selected_rows = c
        suppressed_rows = ()
    else:
        selected = None
        reason = "structure_fail"
        selected_rows = ()
        suppressed_rows = ()

    watch = tuple(
        _candidate(row)
        for row in selected_rows
        if row.watch_eligible
    )
    suppressed = tuple(
        sorted(
            {
                row.playbook_id
                for row in suppressed_rows
            }
        )
    )

    return ClosedBarRuntimeDecision(
        asset_id=asset_id,
        horizon=horizon,
        selected_family=selected,
        reason=reason,
        family_a_structure_present=a_structure,
        family_b_structure_present=b_structure,
        family_c_structure_present=c_structure,
        watch_candidates=watch,
        suppressed_by_precedence=suppressed,
    )
