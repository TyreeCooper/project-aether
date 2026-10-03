from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_kraken_public_probe.py"
)
UTC = timezone.utc
T0 = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_kraken_public_probe_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_assets_are_restricted_to_kraken_seed_crypto() -> None:
    module = _module()
    assert module._assets("BTC,eth") == ("btc", "eth")
    with pytest.raises(ValueError, match="supports only btc,eth"):
        module._assets("btc,eurusd")
    with pytest.raises(ValueError, match="duplicate"):
        module._assets("btc,BTC")


def test_payload_is_explicitly_commissioning_only_and_non_authoritative() -> None:
    module = _module()
    quote = SimpleNamespace(
        asset_id="btc",
        source_id="kraken_public",
        venue="Kraken",
        bid=60000.0,
        ask=60001.0,
        last=60000.5,
        mark=60000.5,
        exchange_ts=T0,
        received_ts=T0,
        adapter_version="fixture",
    )
    print_ = SimpleNamespace(
        asset_id="btc",
        source_id="kraken_public",
        price=60000.5,
        volume=0.01,
        exchange_ts=T0,
        received_ts=T0,
    )
    ticker_batch = SimpleNamespace(
        endpoint="wss://ws.kraken.com/v2",
        status_system="online",
        status_api_version="v2",
        connection_id=1,
        subscription_acknowledged=True,
        requested_symbols=("BTC/USD",),
        quotes=(quote,),
    )
    trade_batch = SimpleNamespace(
        endpoint="wss://ws.kraken.com/v2",
        status_system="online",
        status_api_version="v2",
        connection_id=1,
        subscription_acknowledged=True,
        requested_symbols=("BTC/USD",),
        prints=(print_,),
    )

    payload = module._serialize(ticker_batch, trade_batch)

    assert payload["scope"] == "btc_eth_commissioning_only"
    assert payload["canonical_campaign_1"] is False
    assert payload["phase18_evidence"] is False
    assert payload["database_mutation"] is False
    assert payload["authentication_required"] is False
    assert payload["live_execution_authorized"] is False
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True


def test_probe_has_no_database_or_credential_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "open_vnext_engine" not in source
    assert "VNextStore" not in source
    assert "os.getenv" not in source
    assert "Authorization" not in source
