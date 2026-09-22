from app.pair_book import PairBook
from app.playbooks import playbook_profile, playbook_snapshot
from app.universe import BY_ID
from app.wallet import SpotWallet


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


def test_intraday_playbook_follows_aligned_grain_without_fake_future_fill():
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
    assert snap["executable_signal"] is None
    assert snap["execution_status"] == "long_adapter_required"


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


def test_cash_equity_long_can_execute_when_setup_qualifies():
    daily = _daily(100, start=50.0, step=0.5)
    hourly = _hourly(240, start=80.0, step=0.25)
    minute = _minutes(900, start=120.0, step=0.03)
    snap = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"rth"},
    )
    assert snap["signal"] == "buy"
    assert snap["executable_signal"] == "buy"
    assert snap["execution_status"] == "paper_long_ready"


def test_direct_future_entry_is_blocked_until_contract_adapter_exists():
    book = PairBook(BY_ID["mes"], SpotWallet())
    book.mark = 5000.0
    book.bid = 4999.75
    book.ask = 5000.25
    out = book.enter(
        500.0,
        strategy_snapshot={"mode": "intraday", "risk_stop_pct": 1.0},
    )
    assert out["ok"] is False
    assert out["error"] == "execution_adapter_required"


def test_completed_daily_signal_is_consumed_once():
    bars = _daily(240, step=1.0)
    book = PairBook(BY_ID["btc"], SpotWallet())
    book.seed_daily(bars)
    book.mark = float(bars[-1]["close"])
    book.bid = book.mark - 0.1
    book.ask = book.mark + 0.1

    first = book.snapshot_strategy()
    assert first["executable_signal"] == "buy"
    result = book.enter(100.0, strategy_snapshot=first)
    assert result["ok"] is True
    consumed_key = first["signal_key"]
    assert book.last_entry_signal_key == consumed_key

    book.wallet.sell("btc", book.qty(), book.mark)
    second = book.snapshot_strategy()
    assert second["signal"] == "buy"
    assert second["signal_key"] == consumed_key
    assert second["executable_signal"] is None
    assert second["execution_status"] == "signal_already_consumed"
