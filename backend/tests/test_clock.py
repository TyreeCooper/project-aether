from app.clock import allow_after_losses, close_in_upper_third, is_new_five_minute


def test_five_minute_edge():
    bars = [{"ts": 300, "close": 1}]
    fresh, bucket = is_new_five_minute(bars, None)
    assert fresh and bucket == 300
    again, same = is_new_five_minute(bars, bucket)
    assert not again and same == 300


def test_loss_sit_needs_15m_high():
    bars = []
    px = 100.0
    for i in range(80):
        px += 0.2
        bars.append({"ts": 1_700_000_000 + i * 60, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 1})
    assert allow_after_losses(bars, 0) is True
    assert allow_after_losses(bars, 2) in (True, False)


def test_upper_third_close():
    assert close_in_upper_third({"high": 10, "low": 0, "close": 9})
    assert not close_in_upper_third({"high": 10, "low": 0, "close": 2})
