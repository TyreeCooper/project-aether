from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.registry_runtime import RuntimeRegistryBinding


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_ninjatrader_market_probe.py"
)
UTC = timezone.utc
T0 = datetime(2026, 9, 27, 5, 15, tzinfo=UTC)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_ninjatrader_market_probe_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(asset_id: str, **overrides) -> dict:
    roots = {
        "mes": ("MESZ6", 1001, "US.CME"),
        "mnq": ("MNQZ6", 1002, "US.CME"),
        "mgc": ("MGCZ6", 1003, "US.COMEX"),
        "mcl": ("MCLZ6", 1004, "US.NYMEX"),
        "us10y": ("ZNZ6", 1005, "US.CBOT"),
    }
    contract, contract_id, market_id = roots[asset_id]
    values = {
        "asset_id": asset_id,
        "broker_symbol": contract,
        "primary_market_source_id": NINJATRADER_MARKET_SOURCE_ID,
        "stale_threshold_ms": 1500,
        "calendar_provider_id": "tradinghours_v3",
        "calendar_market_id": market_id,
        "current_contract": contract,
        "market_data_contract_id": contract_id,
        "expiry_utc": T0 + timedelta(days=60),
        "next_contract": contract[:-2] + "H7",
        "source_ref": "test",
    }
    values.update(overrides)
    return {"binding": RuntimeRegistryBinding(**values)}


def test_selected_bindings_preserve_requested_order_and_identity() -> None:
    module = _module()
    selected = module._selected_bindings(
        (_row("mgc"), _row("mes"), _row("mnq")),
        requested_assets=("mes", "mgc"),
    )
    assert tuple(row["binding"].asset_id for row in selected) == (
        "mes",
        "mgc",
    )
    assert module._calendar_map(selected) == {
        "us_fut_idx": "US.CME",
        "us_fut_metal_nrg": "US.COMEX",
    }


def test_selection_rejects_missing_wrong_source_contract_id_or_calendar() -> None:
    module = _module()
    with pytest.raises(RuntimeError, match="binding missing"):
        module._selected_bindings((), requested_assets=("mes",))

    with pytest.raises(RuntimeError, match="not NinjaTrader"):
        module._selected_bindings(
            (_row("mes", primary_market_source_id="other.source"),),
            requested_assets=("mes",),
        )

    with pytest.raises(RuntimeError, match="contractId is missing"):
        module._selected_bindings(
            (_row("mes", market_data_contract_id=None),),
            requested_assets=("mes",),
        )

    with pytest.raises(RuntimeError, match="not TradingHours"):
        module._selected_bindings(
            (_row("mes", calendar_provider_id="other.calendar"),),
            requested_assets=("mes",),
        )

    with pytest.raises(RuntimeError, match="market identity is missing"):
        module._selected_bindings(
            (_row("mes", calendar_market_id=None),),
            requested_assets=("mes",),
        )


def test_market_auth_loader_rejects_trade_token_or_live_host_material() -> None:
    module = _module()
    with pytest.raises(ValueError, match="prohibited"):
        module._load_auth(
            json.dumps(
                {
                    "mdAccessToken": "md-token",
                    "accessToken": "trade-token",
                    "apiHosts": {"mdDemo": "demo.example.test"},
                }
            )
        )

    with pytest.raises(ValueError, match="mdDemo only"):
        module._load_auth(
            json.dumps(
                {
                    "mdAccessToken": "md-token",
                    "apiHosts": {
                        "mdDemo": "demo.example.test",
                        "mdLive": "live.example.test",
                    },
                }
            )
        )


def test_probe_is_explicitly_demo_market_data_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "AETHER_VNEXT_NINJATRADER_MARKET_AUTH_JSON" in source
    assert "AETHER_VNEXT_TRADINGHOURS_API_TOKEN" in source
    assert "fetch_ninjatrader_demo_quote" in source
    assert "require_trade_print=True" in source
    assert '"trade_print"' in source

    prohibited = (
        "accessToken",
        "mdLive",
        "place_order",
        "placeOrder",
        "order/place",
    )
    # The script may mention prohibited credential names only in its explanatory
    # module docstring; it must not consume or parse them.
    executable_source = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith('"""')
    )
    assert "os.getenv(\"accessToken\"" not in executable_source
    assert "os.getenv(\"mdLive\"" not in executable_source
    assert "place_order(" not in executable_source
    assert "placeOrder(" not in executable_source
