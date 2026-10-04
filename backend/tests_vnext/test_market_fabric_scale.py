from __future__ import annotations

import pytest

from aether_vnext.market_fabric_scale import (
    ConsumerCheckpoint,
    LogicalSnapshotBarrier,
    PartitionWatermark,
    ScaleSample,
    SnapshotCompleteness,
    measured_scale_envelope,
    merge_watermarks,
)


def test_logical_snapshot_reports_missing_partition_instead_of_implying_complete() -> None:
    barrier = LogicalSnapshotBarrier(
        expected_partitions=frozenset({"btc_usd", "eth_usd"}),
        watermarks={
            "btc_usd": PartitionWatermark("btc_usd", 100, 1000),
        },
        max_partition_skew_ms=100,
    )

    assert barrier.completeness is SnapshotCompleteness.PARTIAL
    assert barrier.missing_partitions == ("eth_usd",)


def test_complete_snapshot_requires_watermarks_inside_skew_limit() -> None:
    rows = merge_watermarks(
        (
            PartitionWatermark("btc_usd", 100, 1000),
            PartitionWatermark("eth_usd", 80, 1050),
        )
    )
    barrier = LogicalSnapshotBarrier(
        expected_partitions=frozenset({"btc_usd", "eth_usd"}),
        watermarks=rows,
        max_partition_skew_ms=100,
    )
    assert barrier.completeness is SnapshotCompleteness.COMPLETE

    lagging = LogicalSnapshotBarrier(
        expected_partitions=barrier.expected_partitions,
        watermarks={
            "btc_usd": PartitionWatermark("btc_usd", 101, 1000),
            "eth_usd": PartitionWatermark("eth_usd", 81, 1201),
        },
        max_partition_skew_ms=100,
    )
    assert lagging.completeness is SnapshotCompleteness.LAGGING


def test_consumer_checkpoint_is_idempotent_and_cannot_silently_skip() -> None:
    checkpoint = ConsumerCheckpoint(
        consumer_id="strategy",
        offsets={"btc_usd": 5},
    )
    same = checkpoint.commit(partition_id="btc_usd", log_seq=5)
    assert same.offsets["btc_usd"] == 5

    next_one = same.commit(partition_id="btc_usd", log_seq=6)
    assert next_one.offsets["btc_usd"] == 6

    with pytest.raises(ValueError, match="skip"):
        next_one.commit(partition_id="btc_usd", log_seq=8)


def test_scale_envelope_requires_measured_samples() -> None:
    samples = (
        ScaleSample(1000.0, 2.0, 8.0, 1.0, 100),
        ScaleSample(1200.0, 2.5, 9.0, 1.5, 120),
        ScaleSample(900.0, 3.0, 10.0, 2.0, 150),
    )

    envelope = measured_scale_envelope(samples, minimum_samples=3)

    assert envelope.sample_count == 3
    assert envelope.median_events_per_second == 1000.0
    assert envelope.worst_p99_latency_ms == 10.0
    assert envelope.peak_queue_depth == 150
    assert envelope.evidence_only is True

    with pytest.raises(ValueError, match="insufficient"):
        measured_scale_envelope(samples[:1], minimum_samples=3)
