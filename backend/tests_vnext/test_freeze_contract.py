from __future__ import annotations

from aether_vnext.freeze import (
    ALLOCATOR_WEIGHTS,
    ASSET_RISK_FRACTION,
    CLUSTER_RISK_FRACTION,
    CONFIGURATION_HASH,
    CRYPTO_SHORT_DISABLED_PLAYBOOKS,
    EMERGENCY_MAX_OPEN_DEFAULT,
    EMERGENCY_MAX_OPEN_HARD,
    EvidenceState,
    FirmEvidenceState,
    GovernorState,
    OperationalState,
    PORTFOLIO_RISK_FRACTION,
    PRODUCT_SPECS,
    ResearchState,
    SOURCE_FINGERPRINTS,
    TRADE_RISK_FRACTION,
    US10Y_EXECUTABLE_FAMILY,
    US10Y_LEGACY_YIELD_EXECUTION_MATH_ALLOWED,
    US10Y_TICK_POINTS,
    US10Y_TICK_VALUE_USD,
    effective_route_eligible,
    side_supported,
)
from aether_vnext.persistence import (
    DB_SCHEMA,
    NAMESPACE_VERSION,
    canonical_runtime_manifest,
    qualified_table,
)


def test_frozen_state_axes_are_distinct_and_exact() -> None:
    assert [x.value for x in ResearchState] == [
        "HYPOTHESIS",
        "SPEC",
        "FROZEN",
        "RETIRED",
    ]
    assert [x.value for x in EvidenceState] == [
        "CANDIDATE",
        "EVIDENCE_ACCUMULATING",
        "KEEP_PROBATION",
        "KEEP_TRUSTED",
        "CUT_SIZE",
        "BENCH",
    ]
    assert [x.value for x in OperationalState] == ["ENABLED", "DISABLED"]
    assert [x.value for x in GovernorState] == ["NORMAL", "HALT"]
    assert [x.value for x in FirmEvidenceState] == [
        "UNVALIDATED",
        "FIRM_VALIDATED",
    ]


def test_seed_product_side_matrix_is_frozen() -> None:
    assert len(PRODUCT_SPECS) == 12
    assert side_supported("btc", "long") is True
    assert side_supported("btc", "short") is False
    assert side_supported("eth", "short") is False
    assert side_supported("eurusd", "short") is True
    assert side_supported("nvda", "short", locate_ok=False) is False
    assert side_supported("nvda", "short", locate_ok=True) is True
    assert CRYPTO_SHORT_DISABLED_PLAYBOOKS == {
        "pb_crypto_failed_break_v1_3",
        "pb_eth_failed_break_v1_3",
    }


def test_us10y_execution_truth_is_zn_tick_math_only() -> None:
    assert US10Y_EXECUTABLE_FAMILY == "ZN"
    assert US10Y_TICK_POINTS == 1 / 64
    assert US10Y_TICK_VALUE_USD == 15.625
    assert US10Y_LEGACY_YIELD_EXECUTION_MATH_ALLOWED is False


def test_firm_risk_defaults_and_allocator_weights_are_frozen() -> None:
    assert TRADE_RISK_FRACTION == 0.0075
    assert ASSET_RISK_FRACTION == 0.015
    assert CLUSTER_RISK_FRACTION == 0.0225
    assert PORTFOLIO_RISK_FRACTION == 0.03
    assert EMERGENCY_MAX_OPEN_DEFAULT == 4
    assert EMERGENCY_MAX_OPEN_HARD == 6
    assert abs(sum(ALLOCATOR_WEIGHTS.values()) - 1.0) < 1e-12
    assert ALLOCATOR_WEIGHTS == {
        "ros_norm": 0.45,
        "conservative_expectancy_score": 0.20,
        "evidence_quality_score": 0.15,
        "diversification_score": 0.10,
        "execution_quality_score": 0.10,
    }


def test_effective_route_eligibility_keeps_axes_separate() -> None:
    kwargs = dict(
        research_state=ResearchState.FROZEN,
        evidence_state=EvidenceState.CANDIDATE,
        operational_state=OperationalState.ENABLED,
        governor_state=GovernorState.NORMAL,
        asset_id="eurusd",
        side="long",
        market_healthy=True,
        session_eligible=True,
    )
    assert effective_route_eligible(**kwargs) is True
    assert effective_route_eligible(
        **(kwargs | {"evidence_state": EvidenceState.BENCH})
    ) is False
    assert effective_route_eligible(
        **(kwargs | {"operational_state": OperationalState.DISABLED})
    ) is False
    assert effective_route_eligible(
        **(kwargs | {"governor_state": GovernorState.HALT})
    ) is False
    assert effective_route_eligible(
        **(kwargs | {"asset_id": "btc", "side": "short"})
    ) is False


def test_source_fingerprints_and_configuration_hash_are_nonempty() -> None:
    assert set(SOURCE_FINGERPRINTS) == {
        "AETHER_Firm_Master_Blueprint_v5.pdf",
        "AETHER_v1.4_FULL.pdf",
        "AETHER_MASTER_FULL_v5_PLUS_PLAYBOOK_v1.4.pdf",
    }
    assert len(CONFIGURATION_HASH) == 64
    int(CONFIGURATION_HASH, 16)


def test_vnext_persistence_is_namespaced_and_manifest_is_safety_locked() -> None:
    assert DB_SCHEMA == "aether_vnext"
    assert NAMESPACE_VERSION == 1
    assert qualified_table("runtime_manifest") == "aether_vnext.runtime_manifest"
    manifest = canonical_runtime_manifest()
    assert manifest.configuration_hash == CONFIGURATION_HASH
    assert manifest.paper_only is True
    assert manifest.live_blocked is True


def test_qualified_table_rejects_unsafe_names() -> None:
    for bad in ("", "legacy.table", "x;drop table", "with-dash"):
        try:
            qualified_table(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe table name accepted: {bad!r}")
