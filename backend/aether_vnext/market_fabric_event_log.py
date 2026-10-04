"""MF-05b deterministic ordered event log and replay contracts.

The state machine consumes only sequenced, durable-style events with explicit logged
elapsed time. Reducers do not read wall clock, network, randomness, or unordered
external state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Sequence


class EventKind(StrEnum):
    PACKET = "PACKET"
    TICK = "TICK"
    ROUTE = "ROUTE"
    POLICY = "POLICY"
    TRANSPORT = "TRANSPORT"
    HALT = "HALT"
    CLOCK = "CLOCK"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, slots=True)
class OrderedEvent:
    partition_id: str
    log_seq: int
    sequencer_epoch: int
    event_kind: EventKind
    logged_elapsed_ms: int
    event_id: str
    dedupe_key: str
    payload: Mapping[str, object]
    code_revision: str
    policy_revision: str | None = None
    reference_revision: str | None = None

    def __post_init__(self) -> None:
        if not self.partition_id.strip():
            raise ValueError("partition_id is required")
        if self.log_seq < 1:
            raise ValueError("log_seq must be positive")
        if self.sequencer_epoch < 1:
            raise ValueError("sequencer_epoch must be positive")
        if self.logged_elapsed_ms < 0:
            raise ValueError("logged_elapsed_ms cannot be negative")
        if not self.event_id.strip() or not self.dedupe_key.strip():
            raise ValueError("event_id and dedupe_key are required")
        if not self.code_revision.strip():
            raise ValueError("code_revision is required")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def packet_dedupe_key(
    *,
    economic_source_id: str,
    native_event_id: str | None,
    canonical_payload_hash: str,
) -> str:
    source = str(economic_source_id).strip()
    if not source:
        raise ValueError("economic_source_id is required")
    native = None if native_event_id is None else str(native_event_id).strip()
    payload_hash = str(canonical_payload_hash).strip()
    if not payload_hash:
        raise ValueError("canonical_payload_hash is required")
    stable_identity = native or payload_hash
    return f"{source}|{stable_identity}"


@dataclass(slots=True)
class InMemorySequencer:
    partition_id: str
    sequencer_epoch: int
    code_revision: str
    _events: list[OrderedEvent]
    _dedupe: dict[str, OrderedEvent]
    duplicate_count: int

    def __init__(
        self,
        *,
        partition_id: str,
        sequencer_epoch: int,
        code_revision: str,
    ) -> None:
        if not str(partition_id).strip():
            raise ValueError("partition_id is required")
        if sequencer_epoch < 1:
            raise ValueError("sequencer_epoch must be positive")
        if not str(code_revision).strip():
            raise ValueError("code_revision is required")
        self.partition_id = str(partition_id)
        self.sequencer_epoch = int(sequencer_epoch)
        self.code_revision = str(code_revision)
        self._events = []
        self._dedupe = {}
        self.duplicate_count = 0

    @property
    def events(self) -> tuple[OrderedEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        event_kind: EventKind,
        logged_elapsed_ms: int,
        event_id: str,
        dedupe_key: str,
        payload: Mapping[str, object],
        policy_revision: str | None = None,
        reference_revision: str | None = None,
    ) -> OrderedEvent | None:
        if logged_elapsed_ms < 0:
            raise ValueError("logged_elapsed_ms cannot be negative")
        if self._events and logged_elapsed_ms < self._events[-1].logged_elapsed_ms:
            raise ValueError("logged elapsed time cannot move backwards")
        key = str(dedupe_key).strip()
        if not key:
            raise ValueError("dedupe_key is required")
        if key in self._dedupe:
            self.duplicate_count += 1
            return None
        event = OrderedEvent(
            partition_id=self.partition_id,
            log_seq=len(self._events) + 1,
            sequencer_epoch=self.sequencer_epoch,
            event_kind=event_kind,
            logged_elapsed_ms=int(logged_elapsed_ms),
            event_id=str(event_id),
            dedupe_key=key,
            payload=payload,
            code_revision=self.code_revision,
            policy_revision=policy_revision,
            reference_revision=reference_revision,
        )
        self._events.append(event)
        self._dedupe[key] = event
        return event


@dataclass(frozen=True, slots=True)
class ReplayState:
    last_log_seq: int = 0
    last_elapsed_ms: int = 0
    packet_count: int = 0
    tick_count: int = 0
    halted: bool = False
    route_id: str | None = None
    policy_version: str | None = None
    transport_id: str | None = None

    def canonical_payload(self) -> dict[str, object]:
        return {
            "last_log_seq": self.last_log_seq,
            "last_elapsed_ms": self.last_elapsed_ms,
            "packet_count": self.packet_count,
            "tick_count": self.tick_count,
            "halted": self.halted,
            "route_id": self.route_id,
            "policy_version": self.policy_version,
            "transport_id": self.transport_id,
        }

    def state_hash(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def reduce_event(state: ReplayState, event: OrderedEvent) -> ReplayState:
    if event.log_seq != state.last_log_seq + 1:
        raise ValueError("replay requires contiguous log_seq")
    if event.logged_elapsed_ms < state.last_elapsed_ms:
        raise ValueError("replay elapsed time cannot move backwards")

    next_state = replace(
        state,
        last_log_seq=event.log_seq,
        last_elapsed_ms=event.logged_elapsed_ms,
    )
    if event.event_kind is EventKind.PACKET:
        return replace(next_state, packet_count=state.packet_count + 1)
    if event.event_kind is EventKind.TICK:
        return replace(next_state, tick_count=state.tick_count + 1)
    if event.event_kind is EventKind.HALT:
        return replace(next_state, halted=bool(event.payload.get("halted", True)))
    if event.event_kind is EventKind.ROUTE:
        route_id = event.payload.get("route_id")
        if not isinstance(route_id, str) or not route_id.strip():
            raise ValueError("ROUTE event requires route_id")
        return replace(next_state, route_id=route_id)
    if event.event_kind is EventKind.POLICY:
        version = event.payload.get("policy_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("POLICY event requires policy_version")
        return replace(next_state, policy_version=version)
    if event.event_kind is EventKind.TRANSPORT:
        transport_id = event.payload.get("transport_id")
        if not isinstance(transport_id, str) or not transport_id.strip():
            raise ValueError("TRANSPORT event requires transport_id")
        return replace(next_state, transport_id=transport_id)
    return next_state


def replay_hash_stream(
    events: Sequence[OrderedEvent],
    *,
    checkpoint_every: int,
) -> tuple[str, ...]:
    if checkpoint_every < 1:
        raise ValueError("checkpoint_every must be positive")
    state = ReplayState()
    hashes: list[str] = []
    for event in events:
        state = reduce_event(state, event)
        if event.log_seq % checkpoint_every == 0:
            hashes.append(state.state_hash())
    if events and events[-1].log_seq % checkpoint_every:
        hashes.append(state.state_hash())
    return tuple(hashes)
