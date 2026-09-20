from app.market_data.kraken_ws import KrakenWebSocketMarketDataProvider


def test_subscription_message_uses_spot_v2_ticker_shape():
    message = KrakenWebSocketMarketDataProvider.subscription_message("BTC/USD")

    assert message == {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": ["BTC/USD"],
        },
    }


def test_parse_ticker_snapshot():
    message = {
        "channel": "ticker",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "bid": 99_999.0,
                "ask": 100_001.0,
                "last": 100_000.0,
            }
        ],
    }

    snap = KrakenWebSocketMarketDataProvider.parse_ticker_message(message)

    assert snap is not None
    assert snap.symbol == "BTC/USD"
    assert snap.price == 100_000.0
    assert snap.source == "kraken_ws_v2"


def test_parse_non_ticker_message_returns_none():
    assert KrakenWebSocketMarketDataProvider.parse_ticker_message(
        {"channel": "heartbeat"}
    ) is None
