"""Canonical AETHER market-truth authority contract.

This module is deliberately dependency-light. It defines the authority ordering that
all runtime market-data and PAPER execution code must obey. It has no transport,
pricing, strategy, risk, or order side effects.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Final


class MarketTruthLayer(StrEnum):
    ASSET_UNIVERSE = "ASSET_UNIVERSE"
    PROVIDER_CARD = "PROVIDER_CARD"
    ROUTE = "ROUTE"
    MARKET_FABRIC = "MARKET_FABRIC"
    EXECUTION = "EXECUTION"


MARKET_TRUTH_LAYERS: Final = (
    MarketTruthLayer.ASSET_UNIVERSE,
    MarketTruthLayer.PROVIDER_CARD,
    MarketTruthLayer.ROUTE,
    MarketTruthLayer.MARKET_FABRIC,
    MarketTruthLayer.EXECUTION,
)


class ExecutionState(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    STALE = "STALE"
    NOT_OBSERVED = "NOT_OBSERVED"


class EvidenceState(StrEnum):
    NO_WITNESS = "NO_WITNESS"
    CONTESTED = "CONTESTED"
    DIVERGED = "DIVERGED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    DEGRADED = "DEGRADED"
    FULL = "FULL"


class ProviderRole(StrEnum):
    OBSERVE = "observe"
    EXECUTE = "execute"
    BOTH = "both"


FIRST_PROOF_MAX_EXECUTABLE_ROUTES: Final = 1
LIVE_ORDERS_IN_SCOPE: Final = False
AUTOMATIC_EXECUTION_VENUE_SWITCH_ALLOWED: Final = False
WITNESS_CAN_REPLACE_EXECUTABLE_PRICE: Final = False
MISSING_MARKET_FIELD_SENTINEL: Final = None


def assert_layer_transition(upstream: MarketTruthLayer, downstream: MarketTruthLayer) -> None:
    """Reject skipped or reversed authority transitions."""
    left = MARKET_TRUTH_LAYERS.index(upstream)
    right = MARKET_TRUTH_LAYERS.index(downstream)
    if right != left + 1:
        raise ValueError(
            f"market-truth authority must move one layer at a time: "
            f"{upstream.value}->{downstream.value}"
        )
