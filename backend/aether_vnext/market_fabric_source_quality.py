"""MF-06 source-quality scoring and empirical independence contracts.

Quality is observable evidence metadata. It may affect witness admissibility or
Market Intelligence weighting, but it has no path to mutate executable prices.
Effective quorum operates on independence groups, not raw source count.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from types import MappingProxyType
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SourceHealthSnapshot:
    source_id: str
    availability: float
    freshness: float
    continuity: float
    latency: float
    structural_validity: float
    depth_quality: float
    clock_trust: float

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        for name in (
            "availability",
            "freshness",
            "continuity",
            "latency",
            "structural_validity",
            "depth_quality",
            "clock_trust",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class QualityWeightPolicy:
    policy_version: str
    min_weight: float
    max_weight: float
    dimension_weights: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if not 0.0 <= self.min_weight <= self.max_weight <= 1.0:
            raise ValueError("weight bounds must satisfy 0 <= min <= max <= 1")
        allowed = {
            "availability",
            "freshness",
            "continuity",
            "latency",
            "structural_validity",
            "depth_quality",
            "clock_trust",
        }
        normalized = {str(k): float(v) for k, v in self.dimension_weights.items()}
        if not normalized or set(normalized) - allowed:
            raise ValueError("dimension_weights contain unsupported dimensions")
        if any(value < 0 for value in normalized.values()):
            raise ValueError("dimension weights cannot be negative")
        if sum(normalized.values()) <= 0:
            raise ValueError("dimension weights must have positive total weight")
        object.__setattr__(
            self,
            "dimension_weights",
            MappingProxyType(dict(sorted(normalized.items()))),
        )


def bounded_quality_weight(
    snapshot: SourceHealthSnapshot,
    *,
    policy: QualityWeightPolicy,
) -> float:
    numerator = sum(
        float(getattr(snapshot, dimension)) * weight
        for dimension, weight in policy.dimension_weights.items()
    )
    denominator = sum(policy.dimension_weights.values())
    raw = numerator / denominator
    return min(max(raw, policy.min_weight), policy.max_weight)


@dataclass(frozen=True, slots=True)
class IndependencePolicy:
    policy_version: str
    correlation_threshold: float
    min_samples: int

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if not 0.0 < self.correlation_threshold <= 1.0:
            raise ValueError("correlation_threshold must be within (0, 1]")
        if self.min_samples < 3:
            raise ValueError("min_samples must be at least 3")


def pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lx = [float(value) for value in left]
    rx = [float(value) for value in right]
    lmean = sum(lx) / len(lx)
    rmean = sum(rx) / len(rx)
    ldev = [value - lmean for value in lx]
    rdev = [value - rmean for value in rx]
    lvar = sum(value * value for value in ldev)
    rvar = sum(value * value for value in rdev)
    if lvar == 0 or rvar == 0:
        return None
    covariance = sum(a * b for a, b in zip(ldev, rdev))
    return covariance / sqrt(lvar * rvar)


@dataclass(frozen=True, slots=True)
class IndependenceResult:
    source_to_effective_group: Mapping[str, str]
    collapsed_pairs: tuple[tuple[str, str], ...]
    raw_source_count: int
    effective_group_count: int
    policy_version: str


def empirical_independence_groups(
    residual_history: Mapping[str, Sequence[float]],
    *,
    policy: IndependencePolicy,
) -> IndependenceResult:
    sources = tuple(sorted(str(source) for source in residual_history))
    parent = {source: source for source in sources}

    def find(source: str) -> str:
        root = source
        while parent[root] != root:
            root = parent[root]
        while parent[source] != source:
            nxt = parent[source]
            parent[source] = root
            source = nxt
        return root

    def union(left: str, right: str) -> None:
        lroot = find(left)
        rroot = find(right)
        if lroot == rroot:
            return
        winner, loser = sorted((lroot, rroot))
        parent[loser] = winner

    collapsed: list[tuple[str, str]] = []
    for index, left in enumerate(sources):
        for right in sources[index + 1 :]:
            lseries = tuple(float(value) for value in residual_history[left])
            rseries = tuple(float(value) for value in residual_history[right])
            if len(lseries) < policy.min_samples or len(rseries) < policy.min_samples:
                continue
            if len(lseries) != len(rseries):
                continue
            correlation = pearson_correlation(lseries, rseries)
            if correlation is None:
                continue
            if abs(correlation) >= policy.correlation_threshold:
                union(left, right)
                collapsed.append((left, right))

    groups: dict[str, list[str]] = {}
    for source in sources:
        groups.setdefault(find(source), []).append(source)
    canonical_group_id: dict[str, str] = {}
    for members in groups.values():
        group_name = "empirical:" + "+".join(sorted(members))
        for member in members:
            canonical_group_id[member] = group_name

    return IndependenceResult(
        source_to_effective_group=MappingProxyType(
            dict(sorted(canonical_group_id.items()))
        ),
        collapsed_pairs=tuple(sorted(collapsed)),
        raw_source_count=len(sources),
        effective_group_count=len(set(canonical_group_id.values())),
        policy_version=policy.policy_version,
    )
