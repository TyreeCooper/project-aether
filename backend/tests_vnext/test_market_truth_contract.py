from __future__ import annotations

import pytest

from aether_vnext.market_truth_contract import (
    AUTOMATIC_EXECUTION_VENUE_SWITCH_ALLOWED,
    EvidenceState,
    ExecutionState,
    FIRST_PROOF_MAX_EXECUTABLE_ROUTES,
    LIVE_ORDERS_IN_SCOPE,
    MARKET_TRUTH_LAYERS,
    MarketTruthLayer,
    WITNESS_CAN_REPLACE_EXECUTABLE_PRICE,
    assert_layer_transition,
)


def test_market_truth_authority_order_is_exact() -> None:
    assert MARKET_TRUTH_LAYERS == (
        MarketTruthLayer.ASSET_UNIVERSE,
        MarketTruthLayer.PROVIDER_CARD,
        MarketTruthLayer.ROUTE,
        MarketTruthLayer.MARKET_FABRIC,
        MarketTruthLayer.EXECUTION,
    )


def test_execution_and_evidence_axes_are_distinct() -> None:
    assert {row.value for row in ExecutionState} == {
        "EXECUTABLE", "STALE", "NOT_OBSERVED",
    }
    assert {row.value for row in EvidenceState} == {
        "NO_WITNESS", "CONTESTED", "DIVERGED",
        "SINGLE_SOURCE", "DEGRADED", "FULL",
    }
    assert "NOT_OBSERVED" not in {row.value for row in EvidenceState}


def test_market_truth_contract_forbids_cross_layer_shortcuts() -> None:
    assert_layer_transition(MarketTruthLayer.ASSET_UNIVERSE, MarketTruthLayer.PROVIDER_CARD)
    assert_layer_transition(MarketTruthLayer.PROVIDER_CARD, MarketTruthLayer.ROUTE)
    with pytest.raises(ValueError, match="one layer at a time"):
        assert_layer_transition(MarketTruthLayer.ASSET_UNIVERSE, MarketTruthLayer.MARKET_FABRIC)


def test_first_proof_and_live_safety_are_frozen() -> None:
    assert FIRST_PROOF_MAX_EXECUTABLE_ROUTES == 1
    assert LIVE_ORDERS_IN_SCOPE is False
    assert AUTOMATIC_EXECUTION_VENUE_SWITCH_ALLOWED is False
    assert WITNESS_CAN_REPLACE_EXECUTABLE_PRICE is False
