from app.exits import stop_fill_price, time_stop_due


def test_time_stop_needs_age_and_weak_gain():
    assert time_stop_due(180, 0.1, 0.62) is True
    assert time_stop_due(180, 5.0, 0.62) is False
    assert time_stop_due(10, 0.0, 0.62) is False
    assert time_stop_due(None, 0.0, 0.62) is False


def test_stop_fill_matches_replay_slip():
    assert abs(stop_fill_price(100.0) - 99.95) < 1e-9
