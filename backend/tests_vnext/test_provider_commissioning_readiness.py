from __future__ import annotations

from aether_vnext.provider_commissioning_readiness import (
    provider_commissioning_readiness,
)


def test_report_covers_all_seed_assets_without_account_claims() -> None:
    payload = provider_commissioning_readiness()
    assert payload["binding_count"] == 12
    assert payload["strict_import_ready"] is False
    assert payload["credential_values_present"] is False
    assert payload["account_state_source"] == "not_observed"

    providers = {row["provider"]: row for row in payload["providers"]}
    assert set(providers) == {"IBKR", "Kraken", "NinjaTrader", "tastyfx"}
    assert all(
        row["account_state"] == "not_observed"
        for row in providers.values()
    )

    seen = {
        asset_id
        for row in providers.values()
        for asset_id in row["asset_ids"]
    }
    assert seen == set(payload["expected_asset_ids"])


def test_report_exposes_provider_specific_unresolved_facts() -> None:
    payload = provider_commissioning_readiness()
    providers = {row["provider"]: row for row in payload["providers"]}

    ninja = providers["NinjaTrader"]
    assert set(ninja["asset_ids"]) == {"mes", "mnq", "mgc", "mcl", "us10y"}
    assert {
        "broker_symbol",
        "current_contract",
        "market_data_contract_id",
        "expiry_utc",
        "next_contract",
        "stale_threshold_ms",
        "calendar_provider_id",
        "calendar_market_id",
    }.issubset(set(ninja["unresolved_external_fields"]))
    assert any(
        row["source_id"] == "ninjatrader_market_data"
        and row["implemented"] is True
        and row["market_print_implemented"] is True
        for row in ninja["market_source_candidates"]
    )

    ibkr = providers["IBKR"]
    assert set(ibkr["asset_ids"]) == {"nvda", "tsla", "pltr"}
    assert {
        "market_data_contract_id",
        "shortability_provider_id",
        "shortability_stale_threshold_ms",
    }.issubset(set(ibkr["unresolved_external_fields"]))

    crypto = providers["Kraken"]
    assert crypto["unresolved_external_fields"] == ["stale_threshold_ms"]

    fx = providers["tastyfx"]
    assert set(fx["asset_ids"]) == {"eurusd", "usdjpy"}
    assert fx["provider_spec_pending"] is True
