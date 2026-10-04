from __future__ import annotations

from aether_vnext.market_fabric_runtime_identity import (
    commissioned_market_fabric_identity_registry,
    declared_effective_independence_groups,
    runtime_source_identity,
)
from aether_vnext.tape_sources import (
    COINBASE_TAPE_SOURCE_ID,
    DATABENTO_GLBX_TAPE_SOURCE_ID,
    KRAKEN_TAPE_SOURCE_ID,
)


def test_runtime_identity_separates_transport_provider_and_economic_source() -> None:
    databento = runtime_source_identity(DATABENTO_GLBX_TAPE_SOURCE_ID)

    assert databento is not None
    assert databento["provider_id"] == "databento"
    assert databento["economic_source_id"] == "cme_globex"
    assert databento["venue_id"] == "cme_globex"
    assert databento["transport_id"] == DATABENTO_GLBX_TAPE_SOURCE_ID


def test_declared_quorum_counts_independence_groups_not_transport_labels() -> None:
    groups = declared_effective_independence_groups(
        (
            KRAKEN_TAPE_SOURCE_ID,
            COINBASE_TAPE_SOURCE_ID,
        )
    )

    assert groups == (
        "venue:coinbase_exchange",
        "venue:kraken",
    )


def test_unknown_transport_does_not_manufacture_independence_vote() -> None:
    groups = declared_effective_independence_groups(
        (
            KRAKEN_TAPE_SOURCE_ID,
            "unknown_vendor_copy",
        )
    )

    assert groups == ("venue:kraken",)


def test_current_registry_has_no_execution_route_authority() -> None:
    registry = commissioned_market_fabric_identity_registry()

    assert registry.routes == {}
