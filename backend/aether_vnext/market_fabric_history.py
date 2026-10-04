"""MF-08 immutable Market Fabric history, checkpoints, and restore proof.

The historical layer is append-only. It preserves ordered event lineage, raw payload
references, and deterministic state-hash checkpoints so a trade decision can be
reconstructed from durable evidence without rewriting history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Iterable, Mapping

from aether_vnext.market_fabric_event_log import OrderedEvent, replay_hash_stream


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    record_id: str
    partition_id: str
    log_seq: int
    event_id: str
    raw_payload_ref: str | None
    raw_payload_hash: str | None
    code_revision: str
    policy_revision: str | None
    reference_revision: str | None

    def __post_init__(self) -> None:
        for name in ("record_id", "partition_id", "event_id", "code_revision"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.log_seq < 1:
            raise ValueError("log_seq must be positive")
        if self.raw_payload_hash is not None and len(self.raw_payload_hash) != 64:
            raise ValueError("raw_payload_hash must be sha256 hex when present")


@dataclass(frozen=True, slots=True)
class StateCheckpoint:
    partition_id: str
    through_log_seq: int
    state_hash: str
    event_count: int
    manifest_hash: str

    def __post_init__(self) -> None:
        if not self.partition_id.strip():
            raise ValueError("partition_id is required")
        if self.through_log_seq < 1:
            raise ValueError("through_log_seq must be positive")
        if self.event_count < 1:
            raise ValueError("event_count must be positive")
        if len(self.state_hash) != 64 or len(self.manifest_hash) != 64:
            raise ValueError("checkpoint hashes must be sha256 hex")


@dataclass(slots=True)
class AppendOnlyMarketHistory:
    _records: list[HistoryRecord] = field(default_factory=list)
    _by_id: dict[str, HistoryRecord] = field(default_factory=dict)

    @property
    def records(self) -> tuple[HistoryRecord, ...]:
        return tuple(self._records)

    def append(self, record: HistoryRecord) -> None:
        existing = self._by_id.get(record.record_id)
        if existing is not None:
            if existing != record:
                raise ValueError("conflicting immutable history record")
            return
        if self._records:
            prior = self._records[-1]
            if record.partition_id == prior.partition_id and record.log_seq <= prior.log_seq:
                raise ValueError("history log_seq must advance for a partition")
        self._records.append(record)
        self._by_id[record.record_id] = record

    def record_ordered_event(
        self,
        event: OrderedEvent,
        *,
        raw_payload_ref: str | None = None,
        raw_payload_hash: str | None = None,
    ) -> HistoryRecord:
        record = HistoryRecord(
            record_id=f"{event.partition_id}:{event.log_seq}:{event.event_id}",
            partition_id=event.partition_id,
            log_seq=event.log_seq,
            event_id=event.event_id,
            raw_payload_ref=raw_payload_ref,
            raw_payload_hash=raw_payload_hash,
            code_revision=event.code_revision,
            policy_revision=event.policy_revision,
            reference_revision=event.reference_revision,
        )
        self.append(record)
        return record


def _manifest_hash(records: Iterable[HistoryRecord]) -> str:
    payload = [
        {
            "record_id": row.record_id,
            "partition_id": row.partition_id,
            "log_seq": row.log_seq,
            "event_id": row.event_id,
            "raw_payload_ref": row.raw_payload_ref,
            "raw_payload_hash": row.raw_payload_hash,
            "code_revision": row.code_revision,
            "policy_revision": row.policy_revision,
            "reference_revision": row.reference_revision,
        }
        for row in records
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_checkpoint(
    *,
    events: tuple[OrderedEvent, ...],
    records: tuple[HistoryRecord, ...],
) -> StateCheckpoint:
    if not events:
        raise ValueError("events are required")
    if len(events) != len(records):
        raise ValueError("event/history record count mismatch")
    partition = events[0].partition_id
    if any(event.partition_id != partition for event in events):
        raise ValueError("checkpoint requires one partition")
    if any(record.partition_id != partition for record in records):
        raise ValueError("history partition mismatch")
    hashes = replay_hash_stream(events, checkpoint_every=len(events))
    if len(hashes) != 1:
        raise RuntimeError("expected one terminal replay hash")
    return StateCheckpoint(
        partition_id=partition,
        through_log_seq=events[-1].log_seq,
        state_hash=hashes[0],
        event_count=len(events),
        manifest_hash=_manifest_hash(records),
    )


def verify_restore(
    *,
    checkpoint: StateCheckpoint,
    restored_events: tuple[OrderedEvent, ...],
    restored_records: tuple[HistoryRecord, ...],
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    if len(restored_events) != checkpoint.event_count:
        errors.append("event_count_mismatch")
    if len(restored_records) != checkpoint.event_count:
        errors.append("history_record_count_mismatch")
    if restored_events:
        try:
            candidate = build_checkpoint(
                events=restored_events,
                records=restored_records,
            )
        except Exception as exc:
            errors.append(f"checkpoint_rebuild_error:{type(exc).__name__}:{exc}")
        else:
            if candidate.partition_id != checkpoint.partition_id:
                errors.append("partition_mismatch")
            if candidate.through_log_seq != checkpoint.through_log_seq:
                errors.append("log_seq_mismatch")
            if candidate.state_hash != checkpoint.state_hash:
                errors.append("state_hash_mismatch")
            if candidate.manifest_hash != checkpoint.manifest_hash:
                errors.append("manifest_hash_mismatch")
    else:
        errors.append("restored_events_empty")
    return not errors, tuple(errors)


def reconstruct_trade_evidence(
    *,
    decision_ref: str,
    execution_ref: str,
    source_record_ids: tuple[str, ...],
    available_records: Mapping[str, HistoryRecord],
) -> dict[str, object]:
    missing = tuple(
        record_id for record_id in source_record_ids if record_id not in available_records
    )
    return {
        "decision_ref": str(decision_ref),
        "execution_ref": str(execution_ref),
        "source_record_ids": list(source_record_ids),
        "complete": not missing,
        "missing_record_ids": list(missing),
    }
