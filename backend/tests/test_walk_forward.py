from app.learn import CHAMPION, replay


def _bars(count=800):
    bars = []
    px = 100.0
    for i in range(count):
        px += 0.05
        bars.append({
            "ts": 1_700_000_000 + i * 60,
            "open": px - 0.02,
            "high": px + 0.03,
            "low": px - 0.03,
            "close": px,
            "volume": 1.0,
        })
    return bars


def test_replay_start_index_is_respected():
    bars = _bars()
    result = replay(bars, dict(CHAMPION), detailed=True, start_index=750)
    assert result["insufficient_history"] is False
    for trade in result["trade_log"] or []:
        assert int(trade["entry_ts"]) >= int(bars[750]["ts"])
