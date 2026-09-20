from app.venue import parse_binance_book, parse_ohlc_closes, parse_ticker


def test_parse_ticker():
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "a": ["65000.1", "1", "1"],
                "b": ["64999.2", "1", "1"],
                "c": ["65000.0", "0.01"],
            }
        },
    }
    tick = parse_ticker(payload)
    assert tick["source"] == "kraken"
    assert tick["last"] == 65000.0
    assert tick["bid"] == 64999.2
    assert tick["ask"] == 65000.1


def test_parse_ohlc():
    payload = {"error": [], "result": {"XXBTZUSD": [[0, 1, 2, 3, "100.5", 5, 6, 7]]}}
    assert parse_ohlc_closes(payload) == [100.5]


def test_parse_binance_book():
    tick = parse_binance_book(
        {"symbol": "BTCUSD", "bidPrice": "81126.49", "askPrice": "81127.29"}
    )
    assert tick["source"] == "binance.us"
    assert tick["bid"] == 81126.49
    assert tick["ask"] == 81127.29
