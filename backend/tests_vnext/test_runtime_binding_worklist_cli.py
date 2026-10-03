from __future__ import annotations

import importlib.util
from pathlib import Path

from aether_vnext.freeze import CONFIGURATION_HASH


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_runtime_binding_worklist.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_runtime_binding_worklist_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_packet_is_exact_seed12_and_not_import_ready() -> None:
    packet = _module().binding_review_packet()

    assert packet["configuration_hash"] == CONFIGURATION_HASH
    assert packet["registry_version"] is None
    assert packet["ready_for_strict_import"] is False
    assert packet["binding_count"] == 12
    assert set(packet["expected_asset_ids"]) == {
        "btc",
        "eth",
        "eurusd",
        "usdjpy",
        "mes",
        "mnq",
        "mgc",
        "mcl",
        "us10y",
        "nvda",
        "tsla",
        "pltr",
    }


def test_manifest_template_does_not_fabricate_external_values() -> None:
    packet = _module().binding_review_packet()
    manifest = packet["manifest_template"]
    assert manifest["registry_version"] is None
    assert manifest["configuration_hash"] == CONFIGURATION_HASH

    by_asset = {
        row["asset_id"]: row
        for row in manifest["bindings"]
    }

    assert by_asset["btc"]["broker_symbol"] == "XBTUSD"
    assert by_asset["btc"]["primary_market_source_id"] == "kraken_public"
    assert by_asset["btc"]["stale_threshold_ms"] is None

    for asset_id in ("mes", "mnq", "mgc", "mcl", "us10y"):
        assert by_asset[asset_id]["current_contract"] is None
        assert by_asset[asset_id]["market_data_contract_id"] is None
        assert by_asset[asset_id]["expiry_utc"] is None
        assert by_asset[asset_id]["next_contract"] is None

    for asset_id in ("nvda", "tsla", "pltr"):
        assert by_asset[asset_id]["market_data_contract_id"] is None
        assert by_asset[asset_id]["shortability_stale_threshold_ms"] is None

    for row in manifest["bindings"]:
        assert row["source_ref"] is None
