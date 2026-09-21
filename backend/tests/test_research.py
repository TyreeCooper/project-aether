from app.research import parse_binance_klines, validate_bars, walk_forward_v3


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
    assert out["gap_samples"][0]["missing_minutes"] == 2


def test_walk_forward_produces_exact_requested_fold_count():
    bars = []
    px = 100.0
    for i in range(5_000):
        px += 0.02
        bars.append(
            {
                "ts": 1_700_000_000 + i * 60,
                "open": px - 0.01,
                "high": px + 0.03,
                "low": px - 0.03,
                "close": px,
                "volume": 1.0,
            }
        )
    out = walk_forward_v3(bars, folds=4)
    assert out["ok"] is True
    assert out["total_folds"] == 4
    assert len(out["folds"]) == 4
    assert all(fold["oos_end"] >= fold["oos_start"] for fold in out["folds"])
