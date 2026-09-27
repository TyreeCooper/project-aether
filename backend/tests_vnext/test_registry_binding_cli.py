from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.registry_runtime import binding_blockers


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_registry_bindings.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_registry_bindings_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_parser_preserves_operator_binding_values_without_defaults() -> None:
    module = _module()
    payload = {
        "registry_version": "burnin-bindings-2026-09-26",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "btc",
                "broker_symbol": "XBTUSD",
                "primary_market_source_id": "kraken_public",
                "stale_threshold_ms": None,
                "calendar_provider_id": None,
                "source_ref": "operator-reviewed",
            }
        ],
    }

    version, config, bindings = module._parse_manifest(payload)

    assert version == "burnin-bindings-2026-09-26"
    assert config == CONFIGURATION_HASH
    assert bindings[0].stale_threshold_ms is None
    assert binding_blockers(bindings[0]) == ("stale_threshold_missing",)


def test_manifest_parser_rejects_duplicate_assets() -> None:
    module = _module()
    row = {
        "asset_id": "btc",
        "broker_symbol": "XBTUSD",
        "primary_market_source_id": "kraken_public",
        "stale_threshold_ms": 1000,
        "calendar_provider_id": None,
    }
    with pytest.raises(ValueError, match="duplicate asset_id"):
        module._parse_manifest(
            {
                "registry_version": "v1",
                "configuration_hash": CONFIGURATION_HASH,
                "bindings": [row, dict(row)],
            }
        )


def test_manifest_loader_requires_exactly_one_source(tmp_path: Path) -> None:
    module = _module()
    payload = {"registry_version": "v1", "bindings": []}
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one"):
        module._load_payload(
            manifest_json=json.dumps(payload),
            manifest_file=str(path),
        )


def test_cli_exposes_implemented_source_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--require-implemented-source" in source
    assert "require_market_source_implementation" in source
