from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.registry_runtime import (
    binding_blockers,
    runtime_binding_universe,
    runtime_binding_universe_blockers,
)


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


def test_manifest_parser_preserves_ninjatrader_contract_id() -> None:
    module = _module()
    payload = {
        "registry_version": "futures-contract-id-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "mes",
                "broker_symbol": "MESZ6",
                "primary_market_source_id": "ninjatrader_market_data",
                "stale_threshold_ms": 1500,
                "calendar_provider_id": "reviewed.calendar",
                "current_contract": "MESZ6",
                "market_data_contract_id": 987654,
                "expiry_utc": "2026-12-18T14:30:00Z",
                "next_contract": "MESH7",
            }
        ],
    }
    _, _, bindings = module._parse_manifest(payload)
    assert bindings[0].market_data_contract_id == 987654


def test_cli_exposes_implemented_calendar_and_shortability_gates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--require-implemented-calendar" in source
    assert "require_calendar_provider_implementation" in source
    assert "--require-implemented-shortability" in source
    assert "require_shortability_provider_implementation" in source


def test_manifest_parser_preserves_calendar_market_identity() -> None:
    module = _module()
    payload = {
        "registry_version": "calendar-market-id-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "nvda",
                "broker_symbol": "NVDA",
                "primary_market_source_id": "reviewed.equity.source",
                "stale_threshold_ms": 1500,
                "calendar_provider_id": "tradinghours_v3",
                "calendar_market_id": "US.NYSE",
                "shortability_provider_id": "reviewed.locate",
            }
        ],
    }
    _, _, bindings = module._parse_manifest(payload)
    assert bindings[0].calendar_provider_id == "tradinghours_v3"
    assert bindings[0].calendar_market_id == "US.NYSE"


def test_manifest_parser_preserves_shortability_freshness_policy() -> None:
    module = _module()
    payload = {
        "registry_version": "shortability-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "nvda",
                "broker_symbol": "NVDA",
                "primary_market_source_id": "ibkr_webapi_market_data",
                "stale_threshold_ms": 1500,
                "calendar_provider_id": "tradinghours_v3",
                "calendar_market_id": "US.NASDAQ",
                "market_data_contract_id": 4815747,
                "shortability_provider_id": "ibkr_webapi_shortability",
                "shortability_stale_threshold_ms": 2000,
            }
        ],
    }
    _, _, bindings = module._parse_manifest(payload)
    assert bindings[0].shortability_provider_id == "ibkr_webapi_shortability"
    assert bindings[0].shortability_stale_threshold_ms == 2000


def test_seed_universe_detects_partial_runtime_manifest() -> None:
    module = _module()
    payload = {
        "registry_version": "partial-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "btc",
                "broker_symbol": "XBTUSD",
                "primary_market_source_id": "kraken_public",
                "stale_threshold_ms": 1000,
                "calendar_provider_id": None,
            }
        ],
    }
    version, config, bindings = module._parse_manifest(payload)
    universe = runtime_binding_universe(bindings)

    assert version == "partial-v1"
    assert config == CONFIGURATION_HASH
    assert universe.exact is False
    assert "btc" in universe.supplied_asset_ids
    assert set(universe.missing_asset_ids) == set(SEED_REGISTRY) - {"btc"}
    assert runtime_binding_universe_blockers(bindings) == (
        "runtime_binding_seed_universe_missing_assets",
    )


@pytest.mark.asyncio
async def test_strict_partial_manifest_fails_before_database_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    opened = False

    def forbidden_engine():
        nonlocal opened
        opened = True
        raise AssertionError("strict invalid manifest must not open database")

    monkeypatch.setattr(module, "open_vnext_engine", forbidden_engine)
    output = tmp_path / "report.json"
    payload = {
        "registry_version": "partial-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "btc",
                "broker_symbol": "XBTUSD",
                "primary_market_source_id": "kraken_public",
                "stale_threshold_ms": 1000,
                "calendar_provider_id": None,
            }
        ],
    }

    code = await module._main(
        manifest_json=json.dumps(payload),
        manifest_file=None,
        require_complete=True,
        require_seed_universe=True,
        require_implemented_source=True,
        require_implemented_calendar=True,
        require_implemented_shortability=True,
        output=str(output),
    )

    assert code == 2
    assert opened is False
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["persisted"] is False
    assert report["manifest_blockers"] == [
        "runtime_binding_seed_universe_missing_assets"
    ]
    assert set(report["missing_asset_ids"]) == set(SEED_REGISTRY) - {"btc"}


@pytest.mark.asyncio
async def test_validate_only_complete_manifest_never_opens_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    opened = False

    def forbidden_engine():
        nonlocal opened
        opened = True
        raise AssertionError("validate-only mode must not open database")

    monkeypatch.setattr(module, "open_vnext_engine", forbidden_engine)
    output = tmp_path / "validate-only.json"
    payload = {
        "registry_version": "review-only-v1",
        "configuration_hash": CONFIGURATION_HASH,
        "bindings": [
            {
                "asset_id": "btc",
                "broker_symbol": "XBTUSD",
                "primary_market_source_id": "kraken_public",
                "stale_threshold_ms": 1000,
                "calendar_provider_id": None,
                "source_ref": "reviewed-provider-evidence",
            }
        ],
    }

    code = await module._main(
        manifest_json=json.dumps(payload),
        manifest_file=None,
        require_complete=True,
        require_seed_universe=False,
        require_implemented_source=True,
        require_implemented_calendar=True,
        require_implemented_shortability=True,
        output=str(output),
        validate_only=True,
    )

    assert code == 0
    assert opened is False
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["incomplete_binding_count"] == 0
    assert report["validate_only"] is True
    assert report["persisted"] is False


def test_cli_exposes_validate_only_review_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--validate-only" in source
    assert "must not open the database" in source
