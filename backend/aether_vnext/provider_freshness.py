"""Provider timing evidence for reviewed AETHER freshness policy.

This module measures what a provider session actually delivered. It deliberately
does not choose, recommend, or mutate stale-threshold policy. The resulting
statistics are evidence for later operator review of stale_threshold_ms and related
freshness controls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ProviderTimingSample:
    provider_ts_utc: datetime
    received_ts_utc: datetime

    def __post_init__(self) -> None:
        if self.provider_ts_utc.tzinfo is None:
            raise ValueError("provider_ts_utc must be timezone-aware")
        if self.received_ts_utc.tzinfo is None:
            raise ValueError("received_ts_utc must be timezone-aware")
        if self.provider_ts_utc > self.received_ts_utc:
            raise ValueError("provider timestamp cannot follow receive timestamp")


@dataclass(frozen=True, slots=True)
class MillisecondDistribution:
    count: int
    minimum_ms: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    maximum_ms: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("distribution count must be positive")
        if self.minimum_ms < 0:
            raise ValueError("distribution values cannot be negative")
        if not (
            self.minimum_ms
            <= self.p50_ms
            <= self.p95_ms
            <= self.p99_ms
            <= self.maximum_ms
        ):
            raise ValueError("distribution quantiles must be monotonic")


@dataclass(frozen=True, slots=True)
class ProviderTimingEvidence:
    sample_count: int
    observed_span_ms: int
    receive_interarrival: MillisecondDistribution | None
    provider_interarrival: MillisecondDistribution | None
    transport_latency: MillisecondDistribution
    stale_threshold_ms: None = None
    policy_selected: bool = False

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.observed_span_ms < 0:
            raise ValueError("observed_span_ms cannot be negative")
        if self.stale_threshold_ms is not None:
            raise ValueError("timing evidence must not select a stale threshold")
        if self.policy_selected is not False:
            raise ValueError("timing evidence cannot select freshness policy")


def _milliseconds(delta_seconds: float) -> int:
    value = delta_seconds * 1000.0
    if value < 0:
        raise ValueError("timing delta cannot be negative")
    return int(round(value))


def _nearest_rank(sorted_values: tuple[int, ...], percentile: float) -> int:
    if not sorted_values:
        raise ValueError("quantile input must be non-empty")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    rank = max(1, math.ceil(percentile * len(sorted_values)))
    return sorted_values[rank - 1]


def _distribution(values: Iterable[int]) -> MillisecondDistribution:
    ordered = tuple(sorted(int(value) for value in values))
    if not ordered:
        raise ValueError("distribution input must be non-empty")
    if ordered[0] < 0:
        raise ValueError("distribution values cannot be negative")
    return MillisecondDistribution(
        count=len(ordered),
        minimum_ms=ordered[0],
        p50_ms=_nearest_rank(ordered, 0.50),
        p95_ms=_nearest_rank(ordered, 0.95),
        p99_ms=_nearest_rank(ordered, 0.99),
        maximum_ms=ordered[-1],
    )


def measure_provider_timing(
    samples: Iterable[ProviderTimingSample],
) -> ProviderTimingEvidence:
    """Measure provider cadence and transport lag without choosing policy."""
    rows = tuple(samples)
    if not rows:
        raise ValueError("at least one provider timing sample is required")

    prior_receive: datetime | None = None
    prior_provider: datetime | None = None
    receive_gaps: list[int] = []
    provider_gaps: list[int] = []
    latencies: list[int] = []

    for row in rows:
        if prior_receive is not None:
            if row.received_ts_utc <= prior_receive:
                raise ValueError(
                    "received timestamps must be strictly increasing"
                )
            receive_gaps.append(
                _milliseconds(
                    (row.received_ts_utc - prior_receive).total_seconds()
                )
            )
        if prior_provider is not None:
            if row.provider_ts_utc < prior_provider:
                raise ValueError(
                    "provider timestamps must be nondecreasing"
                )
            provider_gaps.append(
                _milliseconds(
                    (row.provider_ts_utc - prior_provider).total_seconds()
                )
            )

        latencies.append(
            _milliseconds(
                (
                    row.received_ts_utc - row.provider_ts_utc
                ).total_seconds()
            )
        )
        prior_receive = row.received_ts_utc
        prior_provider = row.provider_ts_utc

    span_ms = (
        0
        if len(rows) == 1
        else _milliseconds(
            (
                rows[-1].received_ts_utc - rows[0].received_ts_utc
            ).total_seconds()
        )
    )
    return ProviderTimingEvidence(
        sample_count=len(rows),
        observed_span_ms=span_ms,
        receive_interarrival=(
            None if not receive_gaps else _distribution(receive_gaps)
        ),
        provider_interarrival=(
            None if not provider_gaps else _distribution(provider_gaps)
        ),
        transport_latency=_distribution(latencies),
    )
