"""Commissioned runtime identity map for the current Market Fabric lanes.

This module is deliberately explicit: an economic source is not the same object as
the provider that transports it. Direct venue APIs happen to align today for several
crypto lanes; Databento->CME demonstrates why the distinction must remain durable.
"""
from __future__ import annotations

from aether_vnext.market_fabric_identity import (
    EconomicSource,
    MarketFabricIdentityRegistry,
    SourceAuthorityClass,
    TransportLifecycle,
    TransportPath,
)
from aether_vnext.tape_sources import (
    BINANCE_US_TAPE_SOURCE_ID,
    COINBASE_TAPE_SOURCE_ID,
    DATABENTO_GLBX_TAPE_SOURCE_ID,
    GEMINI_TAPE_SOURCE_ID,
    KRAKEN_TAPE_SOURCE_ID,
)


def commissioned_market_fabric_identity_registry() -> MarketFabricIdentityRegistry:
    sources = (
        EconomicSource(
            economic_source_id="kraken_spot",
            market_id="crypto_spot_usd",
            venue_id="kraken",
            independence_group_id="venue:kraken",
            authority_class=SourceAuthorityClass.WITNESS,
        ),
        EconomicSource(
            economic_source_id="coinbase_exchange_spot",
            market_id="crypto_spot_usd",
            venue_id="coinbase_exchange",
            independence_group_id="venue:coinbase_exchange",
            authority_class=SourceAuthorityClass.WITNESS,
        ),
        EconomicSource(
            economic_source_id="binance_us_spot",
            market_id="crypto_spot_usd",
            venue_id="binance_us",
            independence_group_id="venue:binance_us",
            authority_class=SourceAuthorityClass.WITNESS,
        ),
        EconomicSource(
            economic_source_id="gemini_spot",
            market_id="crypto_spot_usd",
            venue_id="gemini",
            independence_group_id="venue:gemini",
            authority_class=SourceAuthorityClass.WITNESS,
        ),
        EconomicSource(
            economic_source_id="cme_globex",
            market_id="listed_futures",
            venue_id="cme_globex",
            independence_group_id="venue:cme_globex",
            authority_class=SourceAuthorityClass.WITNESS,
        ),
    )
    transports = (
        TransportPath(
            transport_id=KRAKEN_TAPE_SOURCE_ID,
            provider_id="kraken_public",
            economic_source_id="kraken_spot",
            adapter_id="aether.adapter.kraken.rest_ticker",
            adapter_version="v1",
            lifecycle_state=TransportLifecycle.ACTIVE,
        ),
        TransportPath(
            transport_id=COINBASE_TAPE_SOURCE_ID,
            provider_id="coinbase_exchange_public",
            economic_source_id="coinbase_exchange_spot",
            adapter_id="aether.adapter.coinbase.book_l1",
            adapter_version="v1",
            lifecycle_state=TransportLifecycle.ACTIVE,
        ),
        TransportPath(
            transport_id=BINANCE_US_TAPE_SOURCE_ID,
            provider_id="binance_us_public",
            economic_source_id="binance_us_spot",
            adapter_id="aether.adapter.binance_us.book_ticker",
            adapter_version="v1",
            lifecycle_state=TransportLifecycle.ACTIVE,
        ),
        TransportPath(
            transport_id=GEMINI_TAPE_SOURCE_ID,
            provider_id="gemini_public",
            economic_source_id="gemini_spot",
            adapter_id="aether.adapter.gemini.pubticker",
            adapter_version="v1",
            lifecycle_state=TransportLifecycle.ACTIVE,
        ),
        TransportPath(
            transport_id=DATABENTO_GLBX_TAPE_SOURCE_ID,
            provider_id="databento",
            economic_source_id="cme_globex",
            adapter_id="aether.adapter.databento.mbp1",
            adapter_version="v1",
            lifecycle_state=TransportLifecycle.STANDBY,
        ),
    )
    return MarketFabricIdentityRegistry.build(
        economic_sources=sources,
        transports=transports,
    )


def runtime_source_identity(source_id: str) -> dict[str, object] | None:
    registry = commissioned_market_fabric_identity_registry()
    transport = registry.transports.get(str(source_id))
    if transport is None:
        return None
    source = registry.economic_sources[transport.economic_source_id]
    return {
        "transport_id": transport.transport_id,
        "provider_id": transport.provider_id,
        "economic_source_id": source.economic_source_id,
        "venue_id": source.venue_id,
        "market_id": source.market_id,
        "declared_independence_group_id": source.independence_group_id,
        "authority_class": source.authority_class.value,
        "adapter_id": transport.adapter_id,
        "adapter_version": transport.adapter_version,
        "transport_lifecycle": transport.lifecycle_state.value,
    }


def declared_effective_independence_groups(
    source_ids: tuple[str, ...],
) -> tuple[str, ...]:
    registry = commissioned_market_fabric_identity_registry()
    known_transport_ids = tuple(
        source_id for source_id in source_ids if source_id in registry.transports
    )
    return registry.transport_independence_groups(
        transport_ids=known_transport_ids,
    )
