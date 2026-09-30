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

from aether_vnext.adapters import KrakenPublicTickerV2, KrakenPublicTradeV2
from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_ADAPTER_VERSION,
    IBKR_WEBAPI_MARKET_PRINT_ADAPTER_VERSION,
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_TRANSPORT_ID,
)
from aether_vnext.ninjatrader_market import (
    NINJATRADER_DEMO_ADAPTER_VERSION,
    NINJATRADER_DEMO_TRANSPORT_ID,
    NINJATRADER_MARKET_PRINT_ADAPTER_VERSION,
    NINJATRADER_MARKET_SOURCE_ID,
)
from aether_vnext.tastyfx_fix_market import (
    TASTYFX_FIX_MARKET_SOURCE_ID,
    TASTYFX_FIX_SUPPORTED_ASSETS,
)


@dataclass(frozen=True, slots=True)
class MarketSourceCapability:
    source_id: str
    transport_id: str
    parser_version: str
    supported_assets: frozenset[str]
    public_market_data: bool
    implemented: bool = True
    market_print_transport_id: str | None = None
    market_print_parser_version: str | None = None

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
            market_print_transport_id="kraken_public_websocket_v2_trade",
            market_print_parser_version=KrakenPublicTradeV2.adapter_version,
        ),
        IBKR_WEBAPI_MARKET_SOURCE_ID: MarketSourceCapability(
            source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
            transport_id=IBKR_WEBAPI_TRANSPORT_ID,
            parser_version=IBKR_WEBAPI_ADAPTER_VERSION,
            supported_assets=frozenset({"nvda", "tsla", "pltr"}),
            public_market_data=False,
            market_print_transport_id=IBKR_WEBAPI_TRANSPORT_ID,
            market_print_parser_version=IBKR_WEBAPI_MARKET_PRINT_ADAPTER_VERSION,
        ),
        NINJATRADER_MARKET_SOURCE_ID: MarketSourceCapability(
            source_id=NINJATRADER_MARKET_SOURCE_ID,
            transport_id=NINJATRADER_DEMO_TRANSPORT_ID,
            parser_version=NINJATRADER_DEMO_ADAPTER_VERSION,
            supported_assets=frozenset(
                {"mes", "mnq", "mgc", "mcl", "us10y"}
            ),
            public_market_data=False,
            market_print_transport_id=NINJATRADER_DEMO_TRANSPORT_ID,
            market_print_parser_version=NINJATRADER_MARKET_PRINT_ADAPTER_VERSION,
        ),
    }
)

PENDING_MARKET_SOURCES: Final = MappingProxyType(
    {
        TASTYFX_FIX_MARKET_SOURCE_ID: MarketSourceCapability(
            source_id=TASTYFX_FIX_MARKET_SOURCE_ID,
            transport_id="fix50sp2_session_provider_spec_pending",
            parser_version="fix50sp2_market_snapshot_bbo_v1",
            supported_assets=TASTYFX_FIX_SUPPORTED_ASSETS,
            public_market_data=False,
            implemented=False,
        )
    }
)


def market_source_capability(
    source_id: str | None,
) -> MarketSourceCapability | None:
    if source_id is None:
        return None
    source = str(source_id).strip()
    return (
        IMPLEMENTED_MARKET_SOURCES.get(source)
        or PENDING_MARKET_SOURCES.get(source)
    )


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
    if capability is None:
        return (
            f"{normalized_role}_market_source_implementation_missing",
        )
    if not capability.implemented:
        if source == TASTYFX_FIX_MARKET_SOURCE_ID:
            return (
                f"{normalized_role}_market_source_provider_spec_pending",
            )
        return (
            f"{normalized_role}_market_source_implementation_missing",
        )
    if not capability.supports_asset(asset_id):
        return (
            f"{normalized_role}_market_source_asset_unsupported",
        )
    return ()



def market_print_implementation_blockers(
    *,
    primary_source_id: str | None,
    fallback_source_id: str | None,
    asset_id: str,
) -> tuple[str, ...]:
    """Require at least one reviewed market source to provide real trade prints.

    Quote/BBO support is not sufficient for completed-bar strategy evaluation.
    The function never treats last-price quote updates as matched trades.
    """
    sources = tuple(
        source
        for source in (
            None if primary_source_id is None else str(primary_source_id).strip(),
            None if fallback_source_id is None else str(fallback_source_id).strip(),
        )
        if source
    )
    if not sources:
        return ("market_print_source_missing",)

    saw_provider_spec_pending = False
    saw_asset_supported = False
    for source in sources:
        capability = market_source_capability(source)
        if capability is None:
            continue
        if not capability.implemented:
            if source == TASTYFX_FIX_MARKET_SOURCE_ID:
                saw_provider_spec_pending = True
            continue
        if not capability.supports_asset(asset_id):
            continue
        saw_asset_supported = True
        if (
            str(capability.market_print_transport_id or "").strip()
            and str(capability.market_print_parser_version or "").strip()
        ):
            return ()

    if saw_provider_spec_pending:
        return ("market_print_source_provider_spec_pending",)
    if saw_asset_supported:
        return ("market_print_source_implementation_missing",)
    return ("market_print_source_asset_unsupported",)
