from aether_vnext.provider_focus_handoff import (
    canonical_seed_asset,
    focus_handoff_rows,
    handoff_payload,
)


def test_seed_symbol_mapping_is_exact_and_provider_aware() -> None:
    assert canonical_seed_asset(provider="Kraken", symbol="BTC/USD") == "btc"
    assert canonical_seed_asset(provider="IBKR", symbol="NVDA") == "nvda"
    assert canonical_seed_asset(provider="tastyfx", symbol="C:EURUSD") == "eurusd"
    assert canonical_seed_asset(
        provider="NinjaTrader",
        symbol="MESZ6",
        product_code="MES",
    ) == "mes"
    assert canonical_seed_asset(provider="IBKR", symbol="AAPL") is None


def test_focus_handoff_queues_all_focused_assets_and_marks_commissioned_assets_ready() -> None:
    rows = focus_handoff_rows([
        {
            "provider": "Kraken",
            "symbol": "BTC/USD",
            "focus_key": "Kraken:BTC/USD",
            "rank": 1,
            "product_code": None,
        },
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "focus_key": "Kraken:SOL/USD",
            "rank": 2,
            "product_code": None,
        },
        {
            "provider": "IBKR",
            "symbol": "NVDA",
            "focus_key": "IBKR:NVDA",
            "rank": 1,
            "product_code": None,
        },
        {
            "provider": "IBKR",
            "symbol": "AAPL",
            "focus_key": "IBKR:AAPL",
            "rank": 2,
            "product_code": None,
        },
    ])
    by_key = {row.focus_key: row for row in rows}
    assert by_key["Kraken:BTC/USD"].state == "SCOUT_RECEIVED"
    assert by_key["Kraken:BTC/USD"].canonical_asset_id == "btc"
    assert by_key["Kraken:SOL/USD"].state == "SCOUT_RECEIVED"
    assert "dynamic_crypto_playbook_binding_required" in by_key["Kraken:SOL/USD"].requirements
    assert by_key["IBKR:NVDA"].state == "SCOUT_RECEIVED"
    assert "strategy_supervisor_not_commissioned_for_asset" in by_key["IBKR:NVDA"].requirements
    assert by_key["IBKR:AAPL"].canonical_asset_id is None
    assert "dynamic_product_registry_binding_required" in by_key["IBKR:AAPL"].requirements

    assert by_key["IBKR:AAPL"].state == "SCOUT_RECEIVED"

    assert by_key["Kraken:BTC/USD"].runtime_evaluable is True
    assert by_key["Kraken:SOL/USD"].runtime_evaluable is False
    assert by_key["IBKR:NVDA"].runtime_evaluable is False
    assert by_key["IBKR:AAPL"].runtime_evaluable is False

    payload = handoff_payload(rows)
    assert sum(row["state"] == "SCOUT_RECEIVED" for row in payload) == 4
    assert sum(row["runtime_evaluable"] is True for row in payload) == 1
    assert all(row["state"] != "DISCOVERY_ONLY" for row in payload)
    assert all(row["state"] != "SCOUT_QUEUED" for row in payload)
