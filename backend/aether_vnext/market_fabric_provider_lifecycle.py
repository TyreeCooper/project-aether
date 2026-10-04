"""MF-10 provider lifecycle and shadow qualification.

A provider transport progresses only through explicit lifecycle gates. Fixture
conformance may open SHADOW. QUALIFIED requires live shadow evidence. STANDBY and
ACTIVE require qualification, and economic-route authority remains separate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Mapping


class ProviderLifecycle(StrEnum):
    DISCOVERED = "DISCOVERED"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    STANDBY = "STANDBY"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    evidence_id: str
    fixture_conformance_passed: bool
    live_shadow_passed: bool
    parity_passed: bool
    rights_reviewed: bool
    provenance_complete: bool
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")


@dataclass(frozen=True, slots=True)
class ProviderLifecycleRecord:
    transport_id: str
    economic_source_id: str
    state: ProviderLifecycle = ProviderLifecycle.DISCOVERED
    qualification_evidence_id: str | None = None
    activation_event_id: str | None = None

    def __post_init__(self) -> None:
        if not self.transport_id.strip():
            raise ValueError("transport_id is required")
        if not self.economic_source_id.strip():
            raise ValueError("economic_source_id is required")


def advance_provider_lifecycle(
    record: ProviderLifecycleRecord,
    *,
    target: ProviderLifecycle,
    evidence: QualificationEvidence | None = None,
    activation_event_id: str | None = None,
) -> ProviderLifecycleRecord:
    current = record.state
    allowed = {
        ProviderLifecycle.DISCOVERED: {ProviderLifecycle.SHADOW, ProviderLifecycle.RETIRED},
        ProviderLifecycle.SHADOW: {ProviderLifecycle.QUALIFIED, ProviderLifecycle.RETIRED},
        ProviderLifecycle.QUALIFIED: {ProviderLifecycle.STANDBY, ProviderLifecycle.ACTIVE, ProviderLifecycle.RETIRED},
        ProviderLifecycle.STANDBY: {ProviderLifecycle.ACTIVE, ProviderLifecycle.RETIRED},
        ProviderLifecycle.ACTIVE: {ProviderLifecycle.STANDBY, ProviderLifecycle.RETIRED},
        ProviderLifecycle.RETIRED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"invalid provider lifecycle transition: {current}->{target}")

    if target is ProviderLifecycle.SHADOW:
        if evidence is None or not evidence.fixture_conformance_passed:
            raise ValueError("SHADOW requires fixture conformance evidence")

    if target in {
        ProviderLifecycle.QUALIFIED,
        ProviderLifecycle.STANDBY,
        ProviderLifecycle.ACTIVE,
    }:
        if evidence is None:
            raise ValueError(f"{target} requires qualification evidence")
        checks = {
            "fixture_conformance_passed": evidence.fixture_conformance_passed,
            "live_shadow_passed": evidence.live_shadow_passed,
            "parity_passed": evidence.parity_passed,
            "rights_reviewed": evidence.rights_reviewed,
            "provenance_complete": evidence.provenance_complete,
        }
        failed = tuple(name for name, passed in checks.items() if not passed)
        if failed:
            raise ValueError(
                f"{target} qualification incomplete: " + ",".join(failed)
            )

    if target is ProviderLifecycle.ACTIVE:
        if not str(activation_event_id or "").strip():
            raise ValueError("ACTIVE requires activation_event_id")

    return replace(
        record,
        state=target,
        qualification_evidence_id=(
            record.qualification_evidence_id
            if evidence is None
            else evidence.evidence_id
        ),
        activation_event_id=(
            record.activation_event_id
            if target is not ProviderLifecycle.ACTIVE
            else str(activation_event_id)
        ),
    )


def economic_route_change_required(
    before: ProviderLifecycleRecord,
    after: ProviderLifecycleRecord,
) -> bool:
    """Transport activation alone never implies an economic-route change."""
    if before.economic_source_id != after.economic_source_id:
        return True
    return False
