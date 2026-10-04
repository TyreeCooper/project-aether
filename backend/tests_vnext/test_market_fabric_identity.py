from __future__ import annotations

import pytest

from aether_vnext.market_fabric_identity import (
    EconomicSource,
    MarketFabricIdentityRegistry,
    RouteAuthorityEvent,
    SourceAuthorityClass,
    TransportLifecycle,
    TransportPath,
)


def _registry() -> MarketFabricIdentityRegistry:
    return MarketFabricIdentityRegistry.build(
        economic_sources=(
            EconomicSource(
                economic_source_id="coinbase_exchange",
                market_id="crypto_spot_usd",
                venue_id="coinbase",
                independence_group_id="venue:coinbase",
                authority_class=SourceAuthorityClass.WITNESS,
            ),
            EconomicSource(
                economic_source_id="kraken_spot",
                market_id="crypto_spot_usd",
                venue_id="kraken",
                independence_group_id="venue:kraken",
                authority_class=SourceAuthorityClass.EXECUTABLE_ROUTE,
            ),
        ),
        transports=(
            TransportPath(
                transport_id="coinbase_direct_ws",
                provider_id="coinbase_direct",
                economic_source_id="coinbase_exchange",
                adapter_id="aether.adapter.coinbase.ws",
                adapter_version="v1",
                lifecycle_state=TransportLifecycle.ACTIVE,
            ),
            TransportPath(
                transport_id="vendor_x_coinbase",
                provider_id="vendor_x",
                economic_source_id="coinbase_exchange",
                adapter_id="aether.adapter.vendor_x.coinbase",
                adapter_version="v1",
                lifecycle_state=TransportLifecycle.QUALIFIED,
            ),
            TransportPath(
                transport_id="kraken_direct_ws",
                provider_id="kraken_direct",
                economic_source_id="kraken_spot",
                adapter_id="aether.adapter.kraken.ws",
                adapter_version="v1",
                lifecycle_state=TransportLifecycle.ACTIVE,
            ),
        ),
    )


def test_two_transports_of_one_source_count_as_one_effective_vote() -> None:
    registry = _registry()

    groups = registry.transport_independence_groups(
        transport_ids=("coinbase_direct_ws", "vendor_x_coinbase"),
    )

    assert groups == ("venue:coinbase",)


def test_distinct_economic_sources_remain_distinct_effective_votes() -> None:
    registry = _registry()

    groups = registry.transport_independence_groups(
        transport_ids=("coinbase_direct_ws", "kraken_direct_ws"),
    )

    assert groups == ("venue:coinbase", "venue:kraken")


def test_route_authority_requires_explicit_signed_event_and_evidence() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="authorization_signature"):
        RouteAuthorityEvent(
            event_id="route-event-1",
            route_id="btc-usd-paper",
            instrument_id="btc_usd",
            from_economic_source_id=None,
            to_economic_source_id="kraken_spot",
            initiator="operator",
            reason="MVF authorized route",
            qualification_evidence_refs=("qual:kraken:001",),
            authorization_signature="",
        )

    event = RouteAuthorityEvent(
        event_id="route-event-2",
        route_id="btc-usd-paper",
        instrument_id="btc_usd",
        from_economic_source_id=None,
        to_economic_source_id="kraken_spot",
        initiator="operator",
        reason="MVF authorized route",
        qualification_evidence_refs=("qual:kraken:001",),
        authorization_signature="operator-signature:test-fixture",
    )

    updated = registry.apply_route_event(event)

    assert updated.routes["btc-usd-paper"].economic_source_id == "kraken_spot"


def test_witness_source_cannot_become_execution_route() -> None:
    registry = _registry()
    event = RouteAuthorityEvent(
        event_id="route-event-3",
        route_id="btc-usd-paper",
        instrument_id="btc_usd",
        from_economic_source_id=None,
        to_economic_source_id="coinbase_exchange",
        initiator="operator",
        reason="invalid fixture",
        qualification_evidence_refs=("qual:coinbase:001",),
        authorization_signature="operator-signature:test-fixture",
    )

    with pytest.raises(ValueError, match="not executable-route qualified"):
        registry.apply_route_event(event)
