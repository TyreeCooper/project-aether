from __future__ import annotations

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.runtime_binding_worklist import (
    binding_template,
    required_external_fields,
    runtime_binding_worklist,
)


EXPECTED = {
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


def test_worklist_covers_exact_seed_universe_and_is_not_import_ready() -> None:
    payload = runtime_binding_worklist()
    assert set(payload["expected_asset_ids"]) == EXPECTED
    assert payload["binding_count"] == 12
    assert payload["configuration_hash"] == CONFIGURATION_HASH
    assert payload["ready_for_strict_import"] is False


def test_template_preserves_only_frozen_seed_bindings() -> None:
    btc = binding_template("btc")
    eth = binding_template("eth")
    mes = binding_template("mes")
    nvda = binding_template("nvda")

    assert btc["broker_symbol"] == "XBTUSD"
    assert btc["primary_market_source_id"] == "kraken_public"
    assert eth["broker_symbol"] == "ETHUSD"
    assert eth["primary_market_source_id"] == "kraken_public"

    assert mes["broker_symbol"] is None
    assert mes["primary_market_source_id"] is None
    assert mes["market_data_contract_id"] is None
    assert nvda["broker_symbol"] is None
    assert nvda["market_data_contract_id"] is None


def test_external_fields_are_explicit_by_family() -> None:
    assert required_external_fields("btc") == ("stale_threshold_ms",)

    futures = set(required_external_fields("mes"))
    assert {
        "broker_symbol",
        "primary_market_source_id",
        "stale_threshold_ms",
        "calendar_provider_id",
        "calendar_market_id",
        "current_contract",
        "market_data_contract_id",
        "expiry_utc",
        "next_contract",
    } == futures

    equity = set(required_external_fields("nvda"))
    assert {
        "broker_symbol",
        "primary_market_source_id",
        "stale_threshold_ms",
        "calendar_provider_id",
        "calendar_market_id",
        "market_data_contract_id",
        "shortability_provider_id",
        "shortability_stale_threshold_ms",
    } == equity


def test_provider_capabilities_are_candidates_not_silent_bindings() -> None:
    payload = runtime_binding_worklist()
    by_asset = {row["asset_id"]: row for row in payload["assets"]}

    mes_sources = by_asset["mes"]["market_source_candidates"]
    assert any(
        row["source_id"] == "ninjatrader_market_data"
        and row["implemented"] is True
        and row["market_print_implemented"] is True
        for row in mes_sources
    )
    assert by_asset["mes"]["template"]["primary_market_source_id"] is None

    nvda_sources = by_asset["nvda"]["market_source_candidates"]
    assert any(
        row["source_id"] == "ibkr_webapi_market_data"
        and row["implemented"] is True
        and row["market_print_implemented"] is True
        for row in nvda_sources
    )
    assert by_asset["nvda"]["template"]["primary_market_source_id"] is None

    fx_sources = by_asset["eurusd"]["market_source_candidates"]
    assert fx_sources == [
        {
            "source_id": "tastyfx_fix_market_data",
            "implemented": False,
            "market_print_implemented": False,
        }
    ]
