from __future__ import annotations

from aether_vnext.market_fabric_source_quality import (
    IndependencePolicy,
    QualityWeightPolicy,
    SourceHealthSnapshot,
    bounded_quality_weight,
    empirical_independence_groups,
)
from aether_vnext.market_fabric_tape import (
    ExecutableTapeSnapshot,
    ExecutionState,
)


def test_quality_weight_is_deterministic_and_bounded() -> None:
    snapshot = SourceHealthSnapshot(
        source_id="coinbase",
        availability=1.0,
        freshness=1.0,
        continuity=0.9,
        latency=0.8,
        structural_validity=1.0,
        depth_quality=0.7,
        clock_trust=1.0,
    )
    policy = QualityWeightPolicy(
        policy_version="quality-fixture-v1",
        min_weight=0.25,
        max_weight=0.90,
        dimension_weights={
            "availability": 1.0,
            "freshness": 2.0,
            "continuity": 1.0,
            "latency": 1.0,
            "structural_validity": 2.0,
            "clock_trust": 2.0,
        },
    )

    first = bounded_quality_weight(snapshot, policy=policy)
    second = bounded_quality_weight(snapshot, policy=policy)

    assert first == second
    assert 0.25 <= first <= 0.90


def test_correlated_sources_collapse_to_one_effective_vote() -> None:
    result = empirical_independence_groups(
        {
            "source-a": (0.1, 0.2, -0.1, 0.3, -0.2, 0.4),
            "source-b": (0.2, 0.4, -0.2, 0.6, -0.4, 0.8),
            "source-c": (0.3, -0.1, 0.4, -0.2, 0.2, -0.3),
        },
        policy=IndependencePolicy(
            policy_version="independence-fixture-v1",
            correlation_threshold=0.99,
            min_samples=5,
        ),
    )

    assert result.raw_source_count == 3
    assert result.effective_group_count == 2
    assert (
        result.source_to_effective_group["source-a"]
        == result.source_to_effective_group["source-b"]
    )
    assert (
        result.source_to_effective_group["source-c"]
        != result.source_to_effective_group["source-a"]
    )


def test_insufficient_history_does_not_manufacture_correlation() -> None:
    result = empirical_independence_groups(
        {
            "source-a": (1.0, 2.0, 3.0),
            "source-b": (2.0, 4.0, 6.0),
        },
        policy=IndependencePolicy(
            policy_version="independence-fixture-v1",
            correlation_threshold=0.90,
            min_samples=5,
        ),
    )

    assert result.effective_group_count == 2
    assert result.collapsed_pairs == ()


def test_quality_scoring_has_no_executable_price_mutation_path() -> None:
    executable = ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-usd-paper",
        authorized_economic_source_id="kraken_spot",
        state=ExecutionState.EXECUTABLE,
        bid=100000.0,
        ask=100002.0,
        last_if_printed=100001.0,
        last_credible_age_ms=20,
    )
    snapshot = SourceHealthSnapshot(
        source_id="witness",
        availability=0.1,
        freshness=0.1,
        continuity=0.1,
        latency=0.1,
        structural_validity=0.1,
        depth_quality=0.1,
        clock_trust=0.1,
    )
    policy = QualityWeightPolicy(
        policy_version="quality-fixture-v1",
        min_weight=0.2,
        max_weight=0.8,
        dimension_weights={"freshness": 1.0, "structural_validity": 1.0},
    )

    bounded_quality_weight(snapshot, policy=policy)

    assert executable.bid == 100000.0
    assert executable.ask == 100002.0
