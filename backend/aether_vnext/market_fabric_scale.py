"""MF-14 cross-partition watermarks, completeness, and measured-scale contracts.

Logical snapshots are explicit about partition completeness. Consumer delivery is
checkpointed and idempotent. Throughput/latency SLO envelopes may only be published
from measured samples; this module does not invent target numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from statistics import median
from typing import Iterable, Mapping, Sequence


class SnapshotCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    LAGGING = "LAGGING"


@dataclass(frozen=True, slots=True)
class PartitionWatermark:
    partition_id: str
    log_seq: int
    logged_elapsed_ms: int

    def __post_init__(self) -> None:
        if not self.partition_id.strip():
            raise ValueError("partition_id is required")
        if self.log_seq < 0:
            raise ValueError("log_seq cannot be negative")
        if self.logged_elapsed_ms < 0:
            raise ValueError("logged_elapsed_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class LogicalSnapshotBarrier:
    expected_partitions: frozenset[str]
    watermarks: Mapping[str, PartitionWatermark]
    max_partition_skew_ms: int

    def __post_init__(self) -> None:
        if not self.expected_partitions:
            raise ValueError("expected_partitions cannot be empty")
        if self.max_partition_skew_ms < 0:
            raise ValueError("max_partition_skew_ms cannot be negative")

    @property
    def missing_partitions(self) -> tuple[str, ...]:
        return tuple(sorted(self.expected_partitions - set(self.watermarks)))

    @property
    def skew_ms(self) -> int | None:
        rows = [
            row.logged_elapsed_ms
            for key, row in self.watermarks.items()
            if key in self.expected_partitions
        ]
        if len(rows) < 2:
            return None
        return max(rows) - min(rows)

    @property
    def completeness(self) -> SnapshotCompleteness:
        if self.missing_partitions:
            return SnapshotCompleteness.PARTIAL
        skew = self.skew_ms
        if skew is not None and skew > self.max_partition_skew_ms:
            return SnapshotCompleteness.LAGGING
        return SnapshotCompleteness.COMPLETE


@dataclass(frozen=True, slots=True)
class ConsumerCheckpoint:
    consumer_id: str
    offsets: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.consumer_id.strip():
            raise ValueError("consumer_id is required")
        if any(int(value) < 0 for value in self.offsets.values()):
            raise ValueError("offsets cannot be negative")

    def commit(self, *, partition_id: str, log_seq: int) -> "ConsumerCheckpoint":
        partition = str(partition_id).strip()
        if not partition:
            raise ValueError("partition_id is required")
        if log_seq < 0:
            raise ValueError("log_seq cannot be negative")
        prior = int(self.offsets.get(partition, 0))
        if log_seq < prior:
            raise ValueError("consumer offset cannot move backwards")
        if log_seq > prior + 1:
            raise ValueError("consumer cannot silently skip offsets")
        updated = dict(self.offsets)
        updated[partition] = log_seq
        return replace(self, offsets=updated)


@dataclass(frozen=True, slots=True)
class ScaleSample:
    events_per_second: float
    p50_latency_ms: float
    p99_latency_ms: float
    jitter_ms: float
    max_queue_depth: int

    def __post_init__(self) -> None:
        values = (
            self.events_per_second,
            self.p50_latency_ms,
            self.p99_latency_ms,
            self.jitter_ms,
        )
        if any(float(value) < 0 for value in values):
            raise ValueError("scale sample metrics cannot be negative")
        if self.max_queue_depth < 0:
            raise ValueError("max_queue_depth cannot be negative")
        if self.p99_latency_ms < self.p50_latency_ms:
            raise ValueError("p99 latency cannot be below p50")


@dataclass(frozen=True, slots=True)
class MeasuredScaleEnvelope:
    sample_count: int
    median_events_per_second: float
    worst_p99_latency_ms: float
    worst_jitter_ms: float
    peak_queue_depth: int
    evidence_only: bool = True


def measured_scale_envelope(
    samples: Sequence[ScaleSample],
    *,
    minimum_samples: int,
) -> MeasuredScaleEnvelope:
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be positive")
    if len(samples) < minimum_samples:
        raise ValueError("insufficient measured scale samples")
    return MeasuredScaleEnvelope(
        sample_count=len(samples),
        median_events_per_second=median(
            sample.events_per_second for sample in samples
        ),
        worst_p99_latency_ms=max(sample.p99_latency_ms for sample in samples),
        worst_jitter_ms=max(sample.jitter_ms for sample in samples),
        peak_queue_depth=max(sample.max_queue_depth for sample in samples),
    )


def merge_watermarks(
    rows: Iterable[PartitionWatermark],
) -> dict[str, PartitionWatermark]:
    out: dict[str, PartitionWatermark] = {}
    for row in rows:
        prior = out.get(row.partition_id)
        if prior is None or (row.log_seq, row.logged_elapsed_ms) > (
            prior.log_seq,
            prior.logged_elapsed_ms,
        ):
            out[row.partition_id] = row
    return dict(sorted(out.items()))
