"""Implemented vNext market-source capability registry.

This registry answers a narrow engineering question: does this repository contain a
concrete parser/transport path for a reviewed market-source ID and asset?

It does not select providers for the operator and it does not turn an unbound source
into a bound one. Missing providers remain explicit blockers.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from aether_vnext.adapters import KrakenPublicTickerV2
from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_ADAPTER_VERSION,
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_TRANSPORT_ID,
)
from aether_vnext.ninjatrader_market import (
    NINJATRADER_DEMO_ADAPTER_VERSION,
    NINJATRADER_DEMO_TRANSPORT_ID,
    NINJATRADER_MARKET_SOURCE_ID,
)


@dataclass(frozen=True, slots=True)
class MarketSourceCapability:
    source_id: str
    transport_id: str
    parser_version: str
    supported_assets: frozenset[str]
    public_market_data: bool
    implemented: bool = True

    def supports_asset(self, asset_id: str) -> bool:
        return str(asset_id).strip().lower() in self.supported_assets


IMPLEMENTED_MARKET_SOURCES: Final = MappingProxyType(
    {
        KrakenPublicTickerV2.adapter_id: MarketSourceCapability(
            source_id=KrakenPublicTickerV2.adapter_id,
            transport_id="kraken_public_websocket_v2",
            parser_version=KrakenPublicTickerV2.adapter_version,
            supported_assets=frozenset({"btc", "eth"}),
            public_market_data=True,
        ),
        IBKR_WEBAPI_MARKET_SOURCE_ID: MarketSourceCapability(
            source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
            transport_id=IBKR_WEBAPI_TRANSPORT_ID,
            parser_version=IBKR_WEBAPI_ADAPTER_VERSION,
            supported_assets=frozenset({"nvda", "tsla", "pltr"}),
            public_market_data=False,
        ),
        NINJATRADER_MARKET_SOURCE_ID: MarketSourceCapability(
            source_id=NINJATRADER_MARKET_SOURCE_ID,
            transport_id=NINJATRADER_DEMO_TRANSPORT_ID,
            parser_version=NINJATRADER_DEMO_ADAPTER_VERSION,
            supported_assets=frozenset(
                {"mes", "mnq", "mgc", "mcl", "us10y"}
            ),
            public_market_data=False,
        ),
    }
)


def market_source_capability(
    source_id: str | None,
) -> MarketSourceCapability | None:
    if source_id is None:
        return None
    return IMPLEMENTED_MARKET_SOURCES.get(str(source_id).strip())


def market_source_implementation_blockers(
    *,
    source_id: str | None,
    asset_id: str,
    role: str,
) -> tuple[str, ...]:
    """Return exact repository implementation blockers for one source binding."""
    normalized_role = str(role).strip().lower()
    if normalized_role not in {"primary", "fallback"}:
        raise ValueError("role must be primary or fallback")

    source = None if source_id is None else str(source_id).strip()
    if not source:
        return (
            f"{normalized_role}_market_source_missing",
        )

    capability = market_source_capability(source)
    if capability is None or not capability.implemented:
        return (
            f"{normalized_role}_market_source_implementation_missing",
        )
    if not capability.supports_asset(asset_id):
        return (
            f"{normalized_role}_market_source_asset_unsupported",
        )
    return ()
