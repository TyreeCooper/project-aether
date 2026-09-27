from __future__ import annotations

from aether_vnext.ibkr_webapi_market import IBKR_WEBAPI_MARKET_SOURCE_ID
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.market_sources import (
    IMPLEMENTED_MARKET_SOURCES,
    market_source_capability,
    market_source_implementation_blockers,
)
from aether_vnext.registry_runtime import (
    RuntimeRegistryBinding,
    binding_blockers,
)


def test_implemented_market_sources_are_explicit_and_asset_scoped() -> None:
    assert set(IMPLEMENTED_MARKET_SOURCES) == {
        "kraken_public",
        IBKR_WEBAPI_MARKET_SOURCE_ID,
        NINJATRADER_MARKET_SOURCE_ID,
    }
    capability = market_source_capability("kraken_public")
    assert capability is not None
    assert capability.implemented is True
    assert capability.public_market_data is True
    assert capability.transport_id == "kraken_public_websocket_v2"
    assert capability.supported_assets == frozenset({"btc", "eth"})

    ibkr = market_source_capability(IBKR_WEBAPI_MARKET_SOURCE_ID)
    assert ibkr is not None
    assert ibkr.implemented is True
    assert ibkr.public_market_data is False
    assert ibkr.transport_id == "ibkr_webapi_smd_websocket"
    assert ibkr.supported_assets == frozenset({"nvda", "tsla", "pltr"})

    ninja = market_source_capability(NINJATRADER_MARKET_SOURCE_ID)
    assert ninja is not None
    assert ninja.implemented is True
    assert ninja.public_market_data is False
    assert ninja.transport_id == "ninjatrader_demo_market_websocket"
    assert ninja.supported_assets == frozenset(
        {"mes", "mnq", "mgc", "mcl", "us10y"}
    )


def test_unknown_reviewed_source_is_not_mistaken_for_implemented_code() -> None:
    assert market_source_implementation_blockers(
        source_id="reviewed.fx.provider",
        asset_id="eurusd",
        role="primary",
    ) == ("primary_market_source_implementation_missing",)


def test_implemented_source_still_rejects_wrong_asset_family() -> None:
    assert market_source_implementation_blockers(
        source_id="kraken_public",
        asset_id="eurusd",
        role="primary",
    ) == ("primary_market_source_asset_unsupported",)


def test_runtime_binding_can_require_repository_source_implementation() -> None:
    btc = RuntimeRegistryBinding(
        asset_id="btc",
        broker_symbol="XBTUSD",
        primary_market_source_id="kraken_public",
        stale_threshold_ms=1000,
        calendar_provider_id=None,
        source_ref="test",
    )
    assert binding_blockers(
        btc,
        require_market_source_implementation=True,
    ) == ()

    fx = RuntimeRegistryBinding(
        asset_id="eurusd",
        broker_symbol="EUR/USD",
        primary_market_source_id="reviewed.fx.provider",
        stale_threshold_ms=1000,
        calendar_provider_id="reviewed.calendar.provider",
        source_ref="test",
    )
    assert binding_blockers(
        fx,
        require_market_source_implementation=True,
    ) == ("primary_market_source_implementation_missing",)


def test_ibkr_market_source_is_equity_only() -> None:
    assert market_source_implementation_blockers(
        source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        asset_id="nvda",
        role="primary",
    ) == ()
    assert market_source_implementation_blockers(
        source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        asset_id="eurusd",
        role="primary",
    ) == ("primary_market_source_asset_unsupported",)


def test_ninjatrader_implemented_source_is_futures_only() -> None:
    assert market_source_implementation_blockers(
        source_id=NINJATRADER_MARKET_SOURCE_ID,
        asset_id="mes",
        role="primary",
    ) == ()
    assert market_source_implementation_blockers(
        source_id=NINJATRADER_MARKET_SOURCE_ID,
        asset_id="nvda",
        role="primary",
    ) == ("primary_market_source_asset_unsupported",)
