"""MF-05d sequencer high-availability and leader-fencing contracts.

Single-writer is a logical invariant. A partition may fail over to a new leader only
through an epoch transition; a fenced prior leader cannot append after takeover.
Durable events remain the source for replay after crash between append and reduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aether_vnext.market_fabric_event_log import EventKind, OrderedEvent


class FencedLeaderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SequencerLease:
    partition_id: str
    leader_id: str
    epoch: int
    fencing_token: str

    def __post_init__(self) -> None:
        if not self.partition_id.strip() or not self.leader_id.strip():
            raise ValueError("partition_id and leader_id are required")
        if self.epoch < 1:
            raise ValueError("epoch must be positive")
        if not self.fencing_token.strip():
            raise ValueError("fencing_token is required")


@dataclass(slots=True)
class ReplicatedPartitionLog:
    partition_id: str
    code_revision: str
    _events: list[OrderedEvent]
    _dedupe: set[str]
    _lease: SequencerLease | None

    def __init__(self, *, partition_id: str, code_revision: str) -> None:
        if not str(partition_id).strip():
            raise ValueError("partition_id is required")
        if not str(code_revision).strip():
            raise ValueError("code_revision is required")
        self.partition_id = str(partition_id)
        self.code_revision = str(code_revision)
        self._events = []
        self._dedupe = set()
        self._lease = None

    @property
    def events(self) -> tuple[OrderedEvent, ...]:
        return tuple(self._events)

    @property
    def current_lease(self) -> SequencerLease | None:
        return self._lease

    def acquire_initial(self, *, leader_id: str) -> SequencerLease:
        if self._lease is not None:
            raise FencedLeaderError("partition already has an active sequencer")
        self._lease = SequencerLease(
            partition_id=self.partition_id,
            leader_id=str(leader_id),
            epoch=1,
            fencing_token=f"{self.partition_id}:epoch:1:{leader_id}",
        )
        return self._lease

    def takeover(
        self,
        *,
        new_leader_id: str,
        expected_prior_epoch: int,
    ) -> SequencerLease:
        if self._lease is None:
            raise FencedLeaderError("cannot takeover partition without prior lease")
        if self._lease.epoch != expected_prior_epoch:
            raise FencedLeaderError("stale takeover request")
        next_epoch = self._lease.epoch + 1
        self._lease = SequencerLease(
            partition_id=self.partition_id,
            leader_id=str(new_leader_id),
            epoch=next_epoch,
            fencing_token=f"{self.partition_id}:epoch:{next_epoch}:{new_leader_id}",
        )
        return self._lease

    def _assert_current(self, lease: SequencerLease) -> None:
        current = self._lease
        if current is None or current != lease:
            raise FencedLeaderError("sequencer lease is fenced")
        if lease.partition_id != self.partition_id:
            raise FencedLeaderError("sequencer lease partition mismatch")

    def append(
        self,
        lease: SequencerLease,
        *,
        event_kind: EventKind,
        logged_elapsed_ms: int,
        event_id: str,
        dedupe_key: str,
        payload: Mapping[str, object],
        policy_revision: str | None = None,
        reference_revision: str | None = None,
    ) -> OrderedEvent | None:
        self._assert_current(lease)
        if logged_elapsed_ms < 0:
            raise ValueError("logged_elapsed_ms cannot be negative")
        if self._events and logged_elapsed_ms < self._events[-1].logged_elapsed_ms:
            raise ValueError("logged elapsed time cannot move backwards")
        key = str(dedupe_key).strip()
        if not key:
            raise ValueError("dedupe_key is required")
        if key in self._dedupe:
            return None
        event = OrderedEvent(
            partition_id=self.partition_id,
            log_seq=len(self._events) + 1,
            sequencer_epoch=lease.epoch,
            event_kind=event_kind,
            logged_elapsed_ms=logged_elapsed_ms,
            event_id=str(event_id),
            dedupe_key=key,
            payload=payload,
            code_revision=self.code_revision,
            policy_revision=policy_revision,
            reference_revision=reference_revision,
        )
        self._events.append(event)
        self._dedupe.add(key)
        return event
