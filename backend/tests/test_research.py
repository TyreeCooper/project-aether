from app.research import parse_binance_klines, validate_bars


def test_parse_binance_klines():
    rows = [[
        1_700_000_000_000,
        "100", "101", "99", "100.5", "2.0",
        1_700_000_059_999,
        "0", 1, "0", "0", "0",
    ]]
    bars = parse_binance_klines(rows)
    assert bars[0]["ts"] == 1_700_000_000
    assert bars[0]["close"] == 100.5


def test_validate_bars_detects_gaps():
    bars = [
        {"ts": 1000, "close": 1},
        {"ts": 1060, "close": 1},
        {"ts": 1240, "close": 1},
    ]
    out = validate_bars(bars)
    assert out["gaps"] == 1
    assert out["ok"] is False
