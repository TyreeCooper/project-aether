from app.desk import completed_bars
from app.pair_book import PairBook
from app.playbooks import playbook_profile, playbook_snapshot
from app.universe import BY_ID
from app.paper_portfolio import PaperPortfolio


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


def test_intraday_playbook_follows_aligned_grain_and_is_paper_executable():
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
    assert snap["execution_status"] == "paper_long_ready"


def test_bearish_setup_is_detected_and_paper_executable():
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
    assert snap["executable_signal"] == "short"
    assert snap["execution_status"] == "paper_short_ready"


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


def test_direct_future_entry_uses_contract_adapter_math():
    book = PairBook(BY_ID["mes"], PaperPortfolio(10_000))
    book.mark = 5000.0
    book.bid = 4999.75
    book.ask = 5000.25
    out = book.enter(
        500.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "intraday",
            "risk_stop_pct": 1.0,
            "signal_key": "mes-test",
        },
        max_capital_usd=3_000,
    )
    assert out["ok"] is True
    assert out["position_side"] == "long"
    assert book.wallet.side("mes") == "long"
    assert book.qty() >= 1


def test_completed_daily_signal_is_consumed_once():
    bars = _daily(240, step=1.0)
    book = PairBook(BY_ID["btc"], PaperPortfolio())
    book.seed_daily(bars)
    book.mark = float(bars[-1]["close"])
    book.bid = book.mark - 0.1
    book.ask = book.mark + 0.1

    first = book.snapshot_strategy()
    assert first["executable_signal"] == "buy"
    result = book.enter(
        100.0,
        strategy_snapshot=first,
        max_capital_usd=1_000,
    )
    assert result["ok"] is True
    consumed_key = first["signal_key"]
    assert book.last_entry_signal_key == consumed_key

    book.wallet.close_position("btc", price=book.mark)
    second = book.snapshot_strategy()
    assert second["signal"] == "buy"
    assert second["signal_key"] == consumed_key
    assert second["executable_signal"] is None
    assert second["execution_status"] == "signal_already_consumed"


def test_completed_bar_filter_keeps_closed_tail_and_drops_forming_tail():
    rows = [
        {"ts": 100, "close": 1.0},
        {"ts": 200, "close": 2.0},
    ]
    forming = completed_bars(rows, 60, now_ts=250)
    assert forming == rows[:-1]

    closed = completed_bars(rows, 60, now_ts=260)
    assert closed == rows


def test_pair_book_can_open_and_close_short_future():
    book = PairBook(BY_ID["mnq"], PaperPortfolio(20_000))
    book.mark = 20_000.0
    book.bid = 19_999.75
    book.ask = 20_000.25
    out = book.enter(
        300.0,
        strategy_snapshot={
            "executable_signal": "short",
            "mode": "intraday",
            "risk_stop_pct": 0.5,
            "signal_key": "mnq-short-test",
        },
        max_capital_usd=5_000,
    )
    assert out["ok"] is True
    assert book.position_side() == "short"
    assert book.stop > book.wallet.avg_entry("mnq")

    book.bars.append(
        {
            "ts": 1_800_000_000,
            "open": 20_000.0,
            "high": 20_000.0,
            "low": 19_900.0,
            "close": 19_900.0,
            "volume": 1.0,
        }
    )
    book.mark = 19_900.0
    book.bid = 19_899.75
    book.ask = 19_900.25
    # Force a protective close through the current stop for deterministic coverage.
    book.stop = 19_900.0
    closed = book.manage()
    assert closed is not None
    assert closed["position_side"] == "short"
    assert book.qty() == 0
