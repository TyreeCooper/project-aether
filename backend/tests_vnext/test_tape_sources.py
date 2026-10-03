from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from aether_vnext.tape import TapeSourceQuality
from aether_vnext.tape_sources import (
    BINANCE_US_TAPE_SOURCE_ID,
    COINBASE_TAPE_SOURCE_ID,
    DATABENTO_GLBX_TAPE_SOURCE_ID,
    KRAKEN_TAPE_SOURCE_ID,
    parse_binance_us_book_ticker,
    parse_coinbase_exchange_ticker,
    parse_databento_mbp1,
    parse_kraken_rest_ticker,
    tape_source_status,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 17, 55, tzinfo=UTC)


def test_public_crypto_sources_normalize_independent_bbo_truth() -> None:
    kraken = parse_kraken_rest_ticker(
        {"error": [], "result": {"XXBTZUSD": {"b": ["99999.0"], "a": ["100001.0"], "c": ["100000.0"]}}},
        asset_id="btc",
        source_symbol="XBTUSD",
        received_at_utc=NOW,
    )
    coinbase = parse_coinbase_exchange_ticker(
        {
            "type": "ticker",
            "product_id": "BTC-USD",
            "price": "100000.25",
            "best_bid": "99999.75",
            "best_ask": "100000.75",
            "time": "2026-10-03T17:54:59.900Z",
        },
        asset_id="btc",
        received_at_utc=NOW,
    )
    binance = parse_binance_us_book_ticker(
        {"symbol": "BTCUSD", "bidPrice": "99999.5", "askPrice": "100000.5"},
        asset_id="btc",
        received_at_utc=NOW,
    )

    assert {kraken.source_id, coinbase.source_id, binance.source_id} == {
        KRAKEN_TAPE_SOURCE_ID,
        COINBASE_TAPE_SOURCE_ID,
        BINANCE_US_TAPE_SOURCE_ID,
    }
    assert all(row.quality is TapeSourceQuality.HEALTHY for row in (kraken, coinbase, binance))
    assert len({row.observation_id for row in (kraken, coinbase, binance)}) == 3


def test_databento_mbp1_uses_reviewed_symbol_and_fixed_price_scale() -> None:
    record = SimpleNamespace(
        levels=[
            SimpleNamespace(
                bid_px=6_800_000_000_000,
                ask_px=6_800_250_000_000,
            )
        ],
        price=6_800_125_000_000,
        ts_event=NOW.timestamp() * 1_000_000_000,
        instrument_id=123456,
    )
    row = parse_databento_mbp1(
        record,
        asset_id="mes",
        source_symbol="MESZ6",
        received_at_utc=NOW,
    )
    assert row is not None
    assert row.source_id == DATABENTO_GLBX_TAPE_SOURCE_ID
    assert row.venue == "CME Globex"
    assert row.source_symbol == "MESZ6"
    assert row.contract_id == "123456"
    assert row.bid == 6800.0
    assert row.ask == 6800.25
    assert row.can_authorize_execution is False


def test_databento_source_reports_credential_requirement_without_key(monkeypatch) -> None:
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    rows = {row["source_id"]: row for row in tape_source_status()}
    assert rows[DATABENTO_GLBX_TAPE_SOURCE_ID]["implemented"] is True
    assert rows[DATABENTO_GLBX_TAPE_SOURCE_ID]["configured"] is False
    assert rows[DATABENTO_GLBX_TAPE_SOURCE_ID]["state"] == "CREDENTIAL_REQUIRED"
    assert rows[KRAKEN_TAPE_SOURCE_ID]["state"] == "READY"
