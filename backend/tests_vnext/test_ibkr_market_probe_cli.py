from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from aether_vnext.ibkr_webapi_market import IBKR_WEBAPI_MARKET_SOURCE_ID
from aether_vnext.registry_runtime import RuntimeRegistryBinding


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_ibkr_market_probe.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_ibkr_market_probe_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(asset_id: str, **overrides) -> dict:
    values = {
        "asset_id": asset_id,
        "broker_symbol": asset_id.upper(),
        "primary_market_source_id": IBKR_WEBAPI_MARKET_SOURCE_ID,
        "stale_threshold_ms": 1500,
        "calendar_provider_id": "tradinghours_v3",
        "calendar_market_id": "US.NASDAQ",
        "market_data_contract_id": {
            "nvda": 4815747,
            "tsla": 76792991,
            "pltr": 444857009,
        }[asset_id],
        "shortability_provider_id": "reviewed.locate",
        "source_ref": "test",
    }
    values.update(overrides)
    return {"binding": RuntimeRegistryBinding(**values)}


def test_selected_bindings_preserve_requested_order_and_reviewed_identity() -> None:
    module = _module()
    rows = (
        _row("pltr"),
        _row("nvda"),
        _row("tsla"),
    )
    selected = module._selected_bindings(
        rows,
        requested_assets=("nvda", "pltr"),
    )

    assert tuple(row["binding"].asset_id for row in selected) == (
        "nvda",
        "pltr",
    )
    assert module._contract_map(selected) == {
        "nvda": 4815747,
        "pltr": 444857009,
    }
    assert module._calendar_map(selected) == {
        "us_rth": "US.NASDAQ",
    }


def test_probe_rejects_missing_or_wrong_runtime_identity() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="binding missing"):
        module._selected_bindings((), requested_assets=("nvda",))

    with pytest.raises(RuntimeError, match="not IBKR"):
        module._selected_bindings(
            (_row("nvda", primary_market_source_id="other.source"),),
            requested_assets=("nvda",),
        )

    with pytest.raises(RuntimeError, match="conid is missing"):
        module._selected_bindings(
            (_row("nvda", market_data_contract_id=None),),
            requested_assets=("nvda",),
        )

    with pytest.raises(RuntimeError, match="not TradingHours"):
        module._selected_bindings(
            (_row("nvda", calendar_provider_id="other.calendar"),),
            requested_assets=("nvda",),
        )

    with pytest.raises(RuntimeError, match="market identity is missing"):
        module._selected_bindings(
            (_row("nvda", calendar_market_id=None),),
            requested_assets=("nvda",),
        )


def test_calendar_map_refuses_conflicting_identity_for_same_calendar() -> None:
    module = _module()
    with pytest.raises(RuntimeError, match="conflicting TradingHours"):
        module._calendar_map(
            (
                _row("nvda", calendar_market_id="US.NASDAQ"),
                _row("tsla", calendar_market_id="US.NYSE"),
            )
        )


def test_probe_is_market_data_only_and_credentials_are_external() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "AETHER_VNEXT_IBKR_SESSION_TOKEN" in source
    assert "AETHER_VNEXT_IBKR_AUTH_MODE" in source
    assert "AETHER_VNEXT_IBKR_WEBSOCKET_URL" in source
    assert "AETHER_VNEXT_TRADINGHOURS_API_TOKEN" in source

    prohibited = (
        "place_order",
        "placeOrder",
        "orders/submit",
        "iserver/account/orders",
    )
    assert all(value not in source for value in prohibited)
