"""MF-05c audited Market Fabric control-plane events.

ROUTE, HALT, POLICY, and TRANSPORT authority changes are explicit ordered events.
Read-only projections cannot mutate authority. HALT closes execution eligibility
without stopping market-data flow or deleting evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Sequence

from aether_vnext.market_fabric_event_log import (
    EventKind,
    InMemorySequencer,
    OrderedEvent,
)
from aether_vnext.market_fabric_identity import RouteAuthorityEvent


class ControlActorRole(StrEnum):
    OPERATOR = "OPERATOR"
    READ_ONLY = "READ_ONLY"


@dataclass(frozen=True, slots=True)
class ControlState:
    route_id: str | None = None
    economic_source_id: str | None = None
    halted: bool = False
    halt_reason: str | None = None
    policy_version: str | None = None
    transport_id: str | None = None
    last_control_log_seq: int = 0

    @property
    def execution_gate_open(self) -> bool:
        return (
            not self.halted
            and self.route_id is not None
            and self.economic_source_id is not None
        )


def _require_operator(actor_role: ControlActorRole) -> None:
    if actor_role is not ControlActorRole.OPERATOR:
        raise PermissionError("read-only actor cannot mutate Market Fabric authority")


def append_route_event(
    sequencer: InMemorySequencer,
    event: RouteAuthorityEvent,
    *,
    actor_role: ControlActorRole,
    logged_elapsed_ms: int,
) -> OrderedEvent:
    _require_operator(actor_role)
    ordered = sequencer.append(
        event_kind=EventKind.ROUTE,
        logged_elapsed_ms=logged_elapsed_ms,
        event_id=event.event_id,
        dedupe_key=f"route:{event.event_id}",
        payload={
            "route_id": event.route_id,
            "instrument_id": event.instrument_id,
            "from_economic_source_id": event.from_economic_source_id,
            "to_economic_source_id": event.to_economic_source_id,
            "initiator": event.initiator,
            "reason": event.reason,
            "qualification_evidence_refs": list(event.qualification_evidence_refs),
            "authorization_signature": event.authorization_signature,
        },
    )
    if ordered is None:
        raise ValueError("duplicate ROUTE event")
    return ordered


def append_halt_event(
    sequencer: InMemorySequencer,
    *,
    event_id: str,
    halted: bool,
    reason: str,
    actor_role: ControlActorRole,
    logged_elapsed_ms: int,
) -> OrderedEvent:
    _require_operator(actor_role)
    normalized_reason = str(reason).strip()
    if not normalized_reason:
        raise ValueError("HALT reason is required")
    ordered = sequencer.append(
        event_kind=EventKind.HALT,
        logged_elapsed_ms=logged_elapsed_ms,
        event_id=event_id,
        dedupe_key=f"halt:{event_id}",
        payload={
            "halted": bool(halted),
            "reason": normalized_reason,
            "actor_role": actor_role.value,
        },
    )
    if ordered is None:
        raise ValueError("duplicate HALT event")
    return ordered


def append_policy_event(
    sequencer: InMemorySequencer,
    *,
    event_id: str,
    policy_version: str,
    actor_role: ControlActorRole,
    logged_elapsed_ms: int,
) -> OrderedEvent:
    _require_operator(actor_role)
    version = str(policy_version).strip()
    if not version:
        raise ValueError("policy_version is required")
    ordered = sequencer.append(
        event_kind=EventKind.POLICY,
        logged_elapsed_ms=logged_elapsed_ms,
        event_id=event_id,
        dedupe_key=f"policy:{event_id}",
        payload={"policy_version": version},
        policy_revision=version,
    )
    if ordered is None:
        raise ValueError("duplicate POLICY event")
    return ordered


def append_transport_event(
    sequencer: InMemorySequencer,
    *,
    event_id: str,
    transport_id: str,
    actor_role: ControlActorRole,
    logged_elapsed_ms: int,
) -> OrderedEvent:
    _require_operator(actor_role)
    transport = str(transport_id).strip()
    if not transport:
        raise ValueError("transport_id is required")
    ordered = sequencer.append(
        event_kind=EventKind.TRANSPORT,
        logged_elapsed_ms=logged_elapsed_ms,
        event_id=event_id,
        dedupe_key=f"transport:{event_id}",
        payload={"transport_id": transport},
    )
    if ordered is None:
        raise ValueError("duplicate TRANSPORT event")
    return ordered


def reduce_control_event(state: ControlState, event: OrderedEvent) -> ControlState:
    if event.event_kind is EventKind.ROUTE:
        route_id = event.payload.get("route_id")
        source_id = event.payload.get("to_economic_source_id")
        signature = event.payload.get("authorization_signature")
        evidence = event.payload.get("qualification_evidence_refs")
        if not isinstance(route_id, str) or not route_id.strip():
            raise ValueError("ROUTE event missing route_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("ROUTE event missing target economic source")
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("ROUTE event missing authorization signature")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("ROUTE event missing qualification evidence")
        return replace(
            state,
            route_id=route_id,
            economic_source_id=source_id,
            last_control_log_seq=event.log_seq,
        )
    if event.event_kind is EventKind.HALT:
        halted = bool(event.payload.get("halted", True))
        reason = event.payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("HALT event missing reason")
        return replace(
            state,
            halted=halted,
            halt_reason=reason if halted else None,
            last_control_log_seq=event.log_seq,
        )
    if event.event_kind is EventKind.POLICY:
        version = event.payload.get("policy_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("POLICY event missing policy_version")
        return replace(
            state,
            policy_version=version,
            last_control_log_seq=event.log_seq,
        )
    if event.event_kind is EventKind.TRANSPORT:
        transport_id = event.payload.get("transport_id")
        if not isinstance(transport_id, str) or not transport_id.strip():
            raise ValueError("TRANSPORT event missing transport_id")
        return replace(
            state,
            transport_id=transport_id,
            last_control_log_seq=event.log_seq,
        )
    return state


def replay_control_state(events: Sequence[OrderedEvent]) -> ControlState:
    state = ControlState()
    for event in events:
        state = reduce_control_event(state, event)
    return state
