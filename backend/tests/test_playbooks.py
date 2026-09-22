from app.playbooks import playbook_profile, playbook_snapshot


def _daily(count=240, start=100.0, step=1.0):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_650_000_000 + i * 86400,
                "open": px - step / 2,
                "high": px + abs(step) * 0.25 + 0.01,
                "low": px - abs(step) * 0.25 - 0.01,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def _hourly(count=240, start=100.0, step=0.25):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_700_000_000 + i * 3600,
                "open": px - step / 2,
                "high": px + abs(step) * 0.20 + 0.01,
                "low": px - abs(step) * 0.20 - 0.01,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def _minutes(count=900, start=100.0, step=0.02):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_700_000_000 + i * 60,
                "open": px - step / 2,
                "high": px + abs(step) * 0.20 + 0.001,
                "low": px - abs(step) * 0.20 - 0.001,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def test_profiles_are_asset_specific():
    assert playbook_profile("eurusd")["primary"] == "intraday"
    assert playbook_profile("mgc")["primary"] == "swing"
    assert playbook_profile("btc")["primary"] == "daily_swing"
    assert playbook_profile("eth")["requires_btc_long"] is True


def test_btc_is_daily_200_20_long_flat():
    bars = _daily(240, step=1.0)
    snap = playbook_snapshot(
        "btc",
        [],
        [],
        bars,
        mark=bars[-1]["close"],
    )
    assert snap["daily_only"] is True
    assert snap["direction"] == "long"
    assert snap["signal"] == "buy"
    assert snap["sma_200"] < snap["daily_close"]


def test_btc_below_200_day_is_flat_and_exits():
    bars = _daily(239, step=1.0)
    last = dict(bars[-1])
    last["ts"] += 86400
    last["close"] = 20.0
    last["open"] = 21.0
    last["high"] = 22.0
    last["low"] = 19.0
    bars.append(last)
    snap = playbook_snapshot(
        "btc",
        [],
        [],
        bars,
        mark=20.0,
        in_position=True,
    )
    assert snap["signal"] is None
    assert snap["reason"] == "below_200d_sma"
    assert snap["exit_signal"] == "sell"


def test_eth_rider_requires_btc_long():
    bars = _daily(240, step=1.0)
    blocked = playbook_snapshot(
        "eth",
        [],
        [],
        bars,
        mark=bars[-1]["close"],
        btc_bias_on=True,
        btc_in_position=False,
    )
    assert blocked["signal"] is None
    assert blocked["reason"] == "btc_rider_gate_closed"

    allowed = playbook_snapshot(
        "eth",
        [],
        [],
        bars,
        mark=bars[-1]["close"],
        btc_bias_on=True,
        btc_in_position=True,
    )
    assert allowed["signal"] == "buy"


def test_intraday_playbook_follows_aligned_grain():
    daily = _daily(100, start=50.0, step=0.5)
    hourly = _hourly(240, start=80.0, step=0.25)
    minute = _minutes(900, start=120.0, step=0.03)
    snap = playbook_snapshot(
        "mes",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"rth"},
    )
    assert snap["daily_grain"] == "long"
    assert snap["four_hour_grain"] == "long"
    assert snap["one_hour_grain"] == "long"
    assert snap["signal"] == "buy"
    assert snap["executable_signal"] == "buy"


def test_bearish_setup_is_detected_but_not_fake_executed():
    daily = _daily(100, start=200.0, step=-0.5)
    hourly = _hourly(240, start=180.0, step=-0.25)
    minute = _minutes(900, start=150.0, step=-0.03)
    snap = playbook_snapshot(
        "mnq",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"rth"},
    )
    assert snap["signal"] == "short"
    assert snap["short_setup_detected"] is True
    assert snap["executable_signal"] is None
    assert snap["execution_status"] == "short_adapter_required"


def test_intraday_entry_is_blocked_outside_required_session():
    daily = _daily(100, start=50.0, step=0.5)
    hourly = _hourly(240, start=80.0, step=0.25)
    minute = _minutes(900, start=120.0, step=0.03)
    snap = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"premarket"},
    )
    assert snap["signal"] is None
    assert snap["reason"] == "session_closed"
