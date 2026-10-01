from aether_vnext.dynamic_products import (
    canonical_provider_asset_id,
    project_kraken_spot_product,
)


def _sol_row():
    return {
        "provider": "Kraken",
        "symbol": "SOL/USD",
        "market_data_symbol": "SOL/USD",
        "execution_symbol": "SOLUSD",
        "asset_class": "spot_crypto",
        "base_currency": "SOL",
        "quote_currency": "USD",
        "quantity_step": 0.001,
        "minimum_quantity": 0.02,
        "minimum_notional": 0.5,
        "tick_size": 0.0001,
    }


def test_dynamic_asset_identity_preserves_seed_ids_and_namespaces_new_assets() -> None:
    assert canonical_provider_asset_id(
        provider="Kraken", symbol="BTC/USD", execution_symbol="XBTUSD"
    ) == "btc"
    assert canonical_provider_asset_id(
        provider="Kraken", symbol="ETH/USD", execution_symbol="ETHUSD"
    ) == "eth"
    assert canonical_provider_asset_id(
        provider="Kraken", symbol="SOL/USD", execution_symbol="SOLUSD"
    ) == "kraken:solusd"


def test_source_complete_usd_kraken_spot_materializes_without_guesses() -> None:
    out = project_kraken_spot_product(
        _sol_row(),
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15_000,
    )
    assert out.asset_id == "kraken:solusd"
    assert out.requirements == ()
    assert out.paper_execution_ready is True
    assert out.product is not None
    assert out.product.broker_symbol == "SOLUSD"
    assert out.product.quantity_step == 0.001
    assert out.product.minimum_quantity == 0.02
    assert out.product.minimum_notional == 0.5
    assert out.product.tick_size == 0.0001
    assert out.product.stale_threshold_ms == 15_000
    assert out.product.long_supported is True
    assert out.product.short_supported is False
    assert out.product.venue_constraints == ("paper_only", "live_hard_blocked")


def test_dynamic_product_refuses_to_invent_missing_provider_facts() -> None:
    row = _sol_row()
    row["quantity_step"] = None
    out = project_kraken_spot_product(
        row,
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15_000,
    )
    assert out.product is None
    assert "quantity_step_missing" in out.requirements


def test_non_usd_kraken_pair_is_received_but_not_mispriced_as_usd() -> None:
    row = _sol_row()
    row["symbol"] = "SOL/EUR"
    row["execution_symbol"] = "SOLEUR"
    row["quote_currency"] = "EUR"
    out = project_kraken_spot_product(
        row,
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15_000,
    )
    assert out.product is None
    assert "usd_settlement_route_required" in out.requirements
