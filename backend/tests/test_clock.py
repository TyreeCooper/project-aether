from app.clock import allow_after_losses, close_in_upper_third, is_new_five_minute


def test_five_minute_edge():
    bars = [{"ts": 300, "close": 1}]
    fresh, bucket = is_new_five_minute(bars, None)
    assert not fresh and bucket == 300
    again, same = is_new_five_minute(bars, bucket)
    assert not again and same == 300
    nxt, new_bucket = is_new_five_minute([{"ts": 600, "close": 1}], bucket)
    assert nxt and new_bucket == 600


def test_loss_sit_needs_15m_high():
    bars = []
    px = 100.0
    for i in range(80):
        px += 0.2
        bars.append({"ts": 1_700_000_000 + i * 60, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 1})
    assert allow_after_losses(bars, 0) is True
    result = allow_after_losses(bars, 2)
    assert isinstance(result, bool)


def test_upper_third_close():
    assert close_in_upper_third({"high": 10, "low": 0, "close": 9})
    assert not close_in_upper_third({"high": 10, "low": 0, "close": 2})


def test_loss_sit_ignores_partial_15m_bucket():
    bars = []
    base = 1_700_000_100
    for i in range(45):
        px = 100 + i * 0.01
        bars.append({
            "ts": base + i * 60,
            "open": px,
            "high": px + 0.02,
            "low": px - 0.02,
            "close": px,
            "volume": 1,
        })
    before = allow_after_losses(bars, 2)
    bars.append({
        "ts": base + 45 * 60,
        "open": 200,
        "high": 210,
        "low": 199,
        "close": 209,
        "volume": 1,
    })
    after = allow_after_losses(bars, 2)
    assert before == after
