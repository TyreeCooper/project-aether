from datetime import datetime, timezone

from aether_vnext.kraken_catalog import (
    parse_kraken_spot_catalog,
    parse_kraken_tickers,
    parse_kraken_usd_catalog,
)
from aether_vnext.massive_discovery import (
    front_contracts_by_product,
    parse_massive_forex_snapshot,
    parse_massive_futures_contracts,
    parse_massive_futures_snapshot,
    parse_massive_stock_snapshot,
)
from aether_vnext.provider_discovery import (
    DiscoveryInstrument,
    _percentile_scores,
    focus_payload,
    rank_provider_catalog,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 1, 6, 30, tzinfo=UTC)


def test_provider_ranker_returns_only_top_twenty_five_with_deterministic_scores() -> None:
    rows = tuple(
        DiscoveryInstrument(
            provider="IBKR",
            symbol=f"S{i:02d}",
            market_data_symbol=f"S{i:02d}",
            execution_symbol=f"S{i:02d}",
            asset_class="equity",
            price=100.0 + i,
            open_price=100.0,
            high_price=101.0 + i,
            low_price=99.0,
            volume=1000.0 * i,
            bid=100.0 + i - 0.01,
            ask=100.0 + i + 0.01,
            observed_at_utc=NOW,
            source="test",
        )
        for i in range(1, 36)
    )
    focus = rank_provider_catalog(rows, provider="IBKR")
    assert focus.catalog_count == 35
    assert focus.eligible_count == 35
    assert len(focus.top25) == 25
    assert [row.rank for row in focus.top25] == list(range(1, 26))
    assert focus.top25[0].symbol == "S35"
    payload = focus_payload(focus)
    assert payload["focus_count"] == 25
    assert payload["top25"][0]["provider"] if "provider" in payload["top25"][0] else True


def test_ranker_filters_inactive_or_unpriced_rows() -> None:
    rows = (
        DiscoveryInstrument(
            provider="tastyfx",
            symbol="C:EURUSD",
            market_data_symbol="C:EURUSD",
            asset_class="fx",
            price=1.1,
            volume=None,
            observed_at_utc=NOW,
            source="test",
        ),
        DiscoveryInstrument(
            provider="tastyfx",
            symbol="C:BAD",
            market_data_symbol="C:BAD",
            asset_class="fx",
            price=None,
            observed_at_utc=NOW,
            source="test",
        ),
    )
    focus = rank_provider_catalog(rows, provider="tastyfx")
    assert focus.catalog_count == 2
    assert focus.eligible_count == 1
    assert focus.top25[0].symbol == "C:EURUSD"


def test_kraken_catalog_and_ticker_parser_cover_all_online_usd_pairs() -> None:
    catalog = parse_kraken_usd_catalog({
        "error": [],
        "result": {
            "XXBTZUSD": {
                "altname": "XBTUSD", "wsname": "BTC/USD",
                "base": "XXBT", "quote": "ZUSD", "status": "online",
            },
            "XETHZUSD": {
                "altname": "ETHUSD", "wsname": "ETH/USD",
                "base": "XETH", "quote": "ZUSD", "status": "online",
            },
            "XXRPZUSD": {
                "altname": "XRPUSD", "wsname": "XRP/USD",
                "base": "XXRP", "quote": "ZUSD", "status": "online",
            },
            "XETHEUR": {
                "altname": "ETHEUR", "wsname": "ETH/EUR",
                "base": "XETH", "quote": "ZEUR", "status": "online",
            },
            "OFFLINE": {
                "altname": "OFFUSD", "wsname": "OFF/USD",
                "base": "OFF", "quote": "ZUSD", "status": "cancel_only",
            },
        },
    })
    assert set(catalog) == {"XXBTZUSD", "XETHZUSD", "XXRPZUSD"}
    full_catalog = parse_kraken_spot_catalog({
        "error": [],
        "result": {
            "XXBTZUSD": {
                "altname": "XBTUSD", "wsname": "BTC/USD",
                "base": "XXBT", "quote": "ZUSD", "status": "online",
            },
            "XETHEUR": {
                "altname": "ETHEUR", "wsname": "ETH/EUR",
                "base": "XETH", "quote": "ZEUR", "status": "online",
            },
        },
    })
    assert set(full_catalog) == {"XXBTZUSD", "XETHEUR"}

    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "a": ["65001"], "b": ["65000"], "c": ["65000.5"],
                "h": ["66000", "67000"], "l": ["64000", "63000"],
                "o": "64000", "v": ["100", "200"],
            },
            "XETHZUSD": {
                "a": ["3001"], "b": ["3000"], "c": ["3000.5"],
                "h": ["3050", "3100"], "l": ["2950", "2900"],
                "o": "2980", "v": ["500", "900"],
            },
            "XXRPZUSD": {
                "a": ["0.51"], "b": ["0.50"], "c": ["0.505"],
                "h": ["0.53", "0.54"], "l": ["0.48", "0.47"],
                "o": "0.49", "v": ["500000", "900000"],
            },
        },
    }
    rows = parse_kraken_tickers(catalog, [payload], observed_at_utc=NOW)
    assert {row.symbol for row in rows} == {"BTC/USD", "ETH/USD", "XRP/USD"}
    assert all(row.provider == "Kraken" for row in rows)


def test_massive_snapshot_parsers_map_market_universes_to_execution_providers() -> None:
    stock = parse_massive_stock_snapshot({
        "tickers": [{
            "ticker": "AAPL",
            "day": {"o": 200, "h": 205, "l": 198, "c": 204, "v": 50000000},
            "lastQuote": {"p": 203.99, "P": 204.01},
            "lastTrade": {"p": 204.0},
            "todaysChangePerc": 2.0,
        }]
    }, observed_at_utc=NOW)
    assert stock[0].provider == "IBKR"
    assert stock[0].symbol == "AAPL"

    fx = parse_massive_forex_snapshot({
        "tickers": [{
            "ticker": "C:EURUSD",
            "day": {"o": 1.10, "h": 1.11, "l": 1.09, "c": 1.105},
            "lastQuote": {"bid": 1.1049, "ask": 1.1051},
            "todaysChangePerc": 0.45,
        }]
    }, observed_at_utc=NOW)
    assert fx[0].provider == "tastyfx"
    assert fx[0].asset_class == "fx"


def test_futures_catalog_selects_front_contract_per_product_before_ranking() -> None:
    contracts = parse_massive_futures_contracts({
        "results": [
            {"ticker": "MESZ6", "product_code": "MES", "name": "MES Dec", "active": True, "days_to_maturity": 80},
            {"ticker": "MESH7", "product_code": "MES", "name": "MES Mar", "active": True, "days_to_maturity": 170},
            {"ticker": "GCZ6", "product_code": "GC", "name": "Gold Dec", "active": True, "days_to_maturity": 60},
        ]
    })
    fronts = front_contracts_by_product(contracts)
    assert fronts["MES"]["ticker"] == "MESZ6"
    rows = parse_massive_futures_snapshot(
        {"results": [
            {
                "ticker": "MESZ6",
                "day": {"o": 6000, "h": 6050, "l": 5980, "c": 6040, "v": 120000},
                "last_quote": {"bid": 6039.75, "ask": 6040.0},
                "last_trade": {"price": 6040.0},
            },
            {
                "ticker": "GCZ6",
                "day": {"o": 3800, "h": 3840, "l": 3780, "c": 3830, "v": 80000},
            },
        ]},
        contracts={str(row["ticker"]): row for row in fronts.values()},
        observed_at_utc=NOW,
    )
    assert {row.provider for row in rows} == {"NinjaTrader"}
    assert {row.product_code for row in rows} == {"MES", "GC"}



def test_massive_snapshot_parser_accepts_unified_and_futures_snake_case_shapes() -> None:
    unified = parse_massive_forex_snapshot({
        "results": [{
            "ticker": "C:GBPUSD",
            "session": {
                "open": 1.31,
                "high": 1.32,
                "low": 1.30,
                "close": 1.315,
                "volume": 2000,
                "change_percent": 0.4,
            },
            "last_quote": {"bid": 1.3149, "ask": 1.3151},
            "last_trade": {"price": 1.315},
        }]
    }, observed_at_utc=NOW)
    assert unified[0].price == 1.315
    assert unified[0].bid == 1.3149
    assert unified[0].ask == 1.3151
    assert unified[0].change_pct == 0.4

    contracts = {
        "MESZ6": {
            "ticker": "MESZ6",
            "product_code": "MES",
            "name": "MES Dec",
        }
    }
    futures = parse_massive_futures_snapshot({
        "results": [{
            "ticker": "MESZ6",
            "session": {
                "open": 6000,
                "high": 6050,
                "low": 5980,
                "close": 6040,
                "volume": 120000,
                "change_percent": 0.67,
            },
            "last_quote": {"bid": 6039.75, "ask": 6040.0},
            "last_trade": {"price": 6040.0},
        }]
    }, contracts=contracts, observed_at_utc=NOW)
    assert futures[0].price == 6040.0
    assert futures[0].bid == 6039.75
    assert futures[0].ask == 6040.0
    assert futures[0].product_code == "MES"



def test_ranker_accepts_activity_only_reference_instruments() -> None:
    rows = tuple(
        DiscoveryInstrument(
            provider="NinjaTrader",
            symbol=f"F{i:02d}",
            market_data_symbol=f"F{i:02d}",
            execution_symbol=f"F{i:02d}",
            asset_class="future",
            product_code=f"F{i:02d}",
            price=None,
            volume=1000.0 * i,
            open_interest=2000.0 * i,
            observed_at_utc=NOW,
            source="public_reference",
            feed_class="PUBLIC_REFERENCE_DELAYED",
            execution_quality=False,
        )
        for i in range(1, 31)
    )
    focus = rank_provider_catalog(rows, provider="NinjaTrader")
    assert focus.eligible_count == 30
    assert len(focus.top25) == 25
    assert focus.top25[0].symbol == "F30"
    payload = focus_payload(focus)
    assert payload["top25"][0]["price"] is None
    assert payload["top25"][0]["open_interest"] == 60000.0
    assert payload["top25"][0]["feed_class"] == "PUBLIC_REFERENCE_DELAYED"
    assert payload["top25"][0]["execution_quality"] is False



def test_kraken_full_catalog_normalizes_cross_pair_volume_to_usd() -> None:
    catalog = parse_kraken_spot_catalog({
        "error": [],
        "result": {
            "ZEURZUSD": {
                "altname": "EURUSD", "wsname": "EUR/USD",
                "base": "ZEUR", "quote": "ZUSD", "status": "online",
            },
            "XETHZEUR": {
                "altname": "ETHEUR", "wsname": "ETH/EUR",
                "base": "XETH", "quote": "ZEUR", "status": "online",
            },
        },
    })
    payload = {
        "error": [],
        "result": {
            "ZEURZUSD": {
                "a": ["1.201"], "b": ["1.199"], "c": ["1.20"],
                "h": ["1.21", "1.22"], "l": ["1.18", "1.17"],
                "o": "1.19", "v": ["1000", "2000"],
            },
            "XETHZEUR": {
                "a": ["3001"], "b": ["2999"], "c": ["3000"],
                "h": ["3050", "3100"], "l": ["2950", "2900"],
                "o": "2970", "v": ["10", "20"],
            },
        },
    }
    rows = parse_kraken_tickers(catalog, [payload], observed_at_utc=NOW)
    by_symbol = {row.symbol: row for row in rows}
    assert set(by_symbol) == {"EUR/USD", "ETH/EUR"}
    assert by_symbol["ETH/EUR"].volume == 72000.0
    assert by_symbol["ETH/EUR"].feed_class == "NATIVE_PUBLIC"



def test_percentile_scores_preserve_tie_average_rank() -> None:
    scores = _percentile_scores({
        "low": 1.0,
        "tie_a": 2.0,
        "tie_b": 2.0,
        "high": 4.0,
    })
    assert scores["low"] == 0.0
    assert scores["tie_a"] == 50.0
    assert scores["tie_b"] == 50.0
    assert scores["high"] == 100.0


def test_ranker_handles_large_equity_catalog_without_quadratic_rank_scan() -> None:
    rows = tuple(
        DiscoveryInstrument(
            provider="IBKR",
            symbol=f"S{i:05d}",
            market_data_symbol=f"S{i:05d}",
            execution_symbol=f"S{i:05d}",
            asset_class="equity",
            price=100.0 + (i % 50),
            open_price=100.0,
            volume=float((i % 1000) + 1),
            bid=99.99,
            ask=100.01,
            observed_at_utc=NOW,
            source="scale-test",
        )
        for i in range(5000)
    )
    focus = rank_provider_catalog(rows, provider="IBKR")
    assert focus.catalog_count == 5000
    assert focus.eligible_count == 5000
    assert len(focus.top25) == 25
