from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ibkr_discovery_cli_restricts_assets_and_secret_free_output() -> None:
    module = _load("aether_vnext_ibkr_instrument_discovery.py")
    assert module._symbols("nvda,TSLA,pltr") == ("NVDA", "TSLA", "PLTR")
    with pytest.raises(ValueError, match="supports only"):
        module._symbols("AAPL")

    payload = module._serialize((), requested_symbols=("NVDA",))
    assert payload["binding_performed"] is False
    assert payload["credential_values_present"] is False
    assert "token" not in str(payload).lower()


def test_ibkr_discovery_cli_rejects_credentials_in_base_url() -> None:
    module = _load("aether_vnext_ibkr_instrument_discovery.py")
    with pytest.raises(ValueError, match="must not contain"):
        module._validated_base_url("https://user:pass@localhost:5000/v1/api")
    with pytest.raises(ValueError, match="must not contain"):
        module._validated_base_url("https://localhost:5000/v1/api?token=x")


def test_ninjatrader_discovery_cli_is_demo_only() -> None:
    module = _load("aether_vnext_ninjatrader_contract_discovery.py")
    assert module._assets("MES,mnq,us10y") == ("mes", "mnq", "us10y")
    assert (
        module._demo_base_url("https://demo.tradovateapi.com/v1/")
        == "https://demo.tradovateapi.com/v1"
    )
    with pytest.raises(ValueError, match="restricted"):
        module._demo_base_url("https://live.tradovateapi.com/v1")
    with pytest.raises(ValueError, match="supports only"):
        module._assets("es")


def test_ninjatrader_output_does_not_claim_binding_or_credentials() -> None:
    module = _load("aether_vnext_ninjatrader_contract_discovery.py")
    payload = module._serialize({"mes": ()})
    assert payload["binding_performed"] is False
    assert payload["credential_values_present"] is False
    assert payload["assets"][0]["query_symbol"] == "MES"
