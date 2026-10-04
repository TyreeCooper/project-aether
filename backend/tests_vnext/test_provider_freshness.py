from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.provider_freshness import (
    ProviderTimingSample,
    measure_provider_timing,
    provider_timing_evidence_payload,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)


def _sample(provider_ms: int, receive_ms: int) -> ProviderTimingSample:
    return ProviderTimingSample(
        provider_ts_utc=T0 + timedelta(milliseconds=provider_ms),
        received_ts_utc=T0 + timedelta(milliseconds=receive_ms),
    )


def test_measurement_reports_cadence_and_latency_without_policy() -> None:
    evidence = measure_provider_timing(
        (
            _sample(0, 10),
            _sample(100, 125),
            _sample(250, 280),
            _sample(400, 440),
        )
    )

    assert evidence.sample_count == 4
    assert evidence.observed_span_ms == 430
    assert evidence.receive_interarrival is not None
    assert evidence.receive_interarrival.minimum_ms == 115
    assert evidence.receive_interarrival.maximum_ms == 160
    assert evidence.provider_interarrival is not None
    assert evidence.provider_interarrival.minimum_ms == 100
    assert evidence.provider_interarrival.maximum_ms == 150
    assert evidence.transport_latency.minimum_ms == 10
    assert evidence.transport_latency.maximum_ms == 40
    assert evidence.stale_threshold_ms is None
    assert evidence.policy_selected is False


def test_nearest_rank_quantiles_are_deterministic() -> None:
    evidence = measure_provider_timing(
        tuple(
            _sample(index * 100, index * 100 + latency)
            for index, latency in enumerate(
                (1, 2, 3, 4, 5, 6, 7, 8, 9, 100),
            )
        )
    )

    latency = evidence.transport_latency
    assert latency.p50_ms == 5
    assert latency.p95_ms == 100
    assert latency.p99_ms == 100


def test_single_sample_measures_latency_but_not_interarrival() -> None:
    evidence = measure_provider_timing((_sample(100, 130),))
    assert evidence.observed_span_ms == 0
    assert evidence.receive_interarrival is None
    assert evidence.provider_interarrival is None
    assert evidence.transport_latency.count == 1
    assert evidence.transport_latency.p99_ms == 30


def test_out_of_order_receive_or_provider_time_fails_closed() -> None:
    with pytest.raises(ValueError, match="received timestamps"):
        measure_provider_timing(
            (
                _sample(0, 20),
                _sample(10, 20),
            )
        )

    with pytest.raises(ValueError, match="provider timestamps"):
        measure_provider_timing(
            (
                _sample(10, 20),
                ProviderTimingSample(
                    provider_ts_utc=T0 + timedelta(milliseconds=5),
                    received_ts_utc=T0 + timedelta(milliseconds=30),
                ),
            )
        )


def test_provider_timestamp_after_receive_fails_closed() -> None:
    with pytest.raises(ValueError, match="cannot follow"):
        ProviderTimingSample(
            provider_ts_utc=T0 + timedelta(milliseconds=20),
            received_ts_utc=T0 + timedelta(milliseconds=10),
        )


def test_equal_provider_timestamps_are_preserved_as_zero_gap() -> None:
    evidence = measure_provider_timing(
        (
            _sample(0, 10),
            _sample(0, 20),
        )
    )
    assert evidence.provider_interarrival is not None
    assert evidence.provider_interarrival.minimum_ms == 0
    assert evidence.provider_interarrival.maximum_ms == 0


def test_serialized_evidence_cannot_smuggle_a_policy_choice() -> None:
    payload = provider_timing_evidence_payload(
        measure_provider_timing((_sample(100, 130),))
    )
    assert payload["stale_threshold_ms"] is None
    assert payload["policy_selected"] is False
    assert payload["transport_latency"]["p99_ms"] == 30
