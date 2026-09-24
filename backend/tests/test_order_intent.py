from app.fill_model import modeled_fill_price
from app.order_intent import TwoPhaseExecutor, idempotency_key
from app.sleeves import SleeveBook


def _exec():
    return TwoPhaseExecutor(SleeveBook.seed(10_000), paper_ack_ms=0, submit_timeout_ms=50)


def test_phase_a_does_not_consume_signal():
    ex = _exec()
    out = ex.reserve(
        ticket_id="t1",
        asset_id="btc",
        horizon="daily_swing",
        side="long",
        quantity=0.01,
        reserved_usd=1_000,
        signal_key="sig-1",
    )
    assert out["ok"] is True
    assert out["state"] == "RESERVED"
    assert out["consumed_signal"] is False
    assert "sig-1" not in ex.consumed_signals
    assert "SUBMITTED" not in out["events"]


def test_submit_then_fill_consumes_signal_once():
    ex = _exec()
    reserved = ex.reserve(
        ticket_id="t1",
        asset_id="nvda",
        horizon="intraday",
        side="long",
        quantity=10,
        reserved_usd=1_000,
        signal_key="sig-nvda",
    )
    submitted = ex.submit(reserved["order_intent_id"])
    assert submitted["state"] == "SUBMITTED"
    filled = ex.fill(
        reserved["order_intent_id"],
        bid=99.0,
        ask=100.0,
        mark=99.5,
    )
    assert filled["ok"] is True
    assert filled["state"] == "FILLED"
    assert filled["consumed_signal"] is True
    assert "sig-nvda" in ex.consumed_signals
    assert filled["events"] == ["RESERVED", "SUBMITTED", "FILLED"]
    expected = modeled_fill_price("buy", bid=99.0, ask=100.0, mark=99.5)
    assert filled["fill_price"] == expected
    assert ex.sleeves.sleeve("ibkr_paper").cash_reserved_usd == 0.0


def test_idempotent_reserve_does_not_double_hold():
    ex = _exec()
    kwargs = dict(
        ticket_id="t1",
        asset_id="eurusd",
        horizon="intraday",
        side="long",
        quantity=10_000,
        reserved_usd=550,
        signal_key="fx-1",
    )
    first = ex.reserve(**kwargs)
    second = ex.reserve(**kwargs)
    assert first["ok"] and second["ok"]
    assert second["duplicate"] is True
    assert first["order_intent_id"] == second["order_intent_id"]
    assert ex.sleeves.sleeve("tastyfx_paper").cash_reserved_usd == 550.0


def test_reject_releases_reserve_and_does_not_consume_signal():
    ex = _exec()
    reserved = ex.reserve(
        ticket_id="t1",
        asset_id="mes",
        horizon="intraday",
        side="long",
        quantity=1,
        reserved_usd=1_200,
        signal_key="mes-1",
    )
    ex.submit(reserved["order_intent_id"])
    out = ex.reject(reserved["order_intent_id"], "market_changed")
    assert out["state"] == "REJECTED"
    assert "mes-1" not in ex.consumed_signals
    assert ex.sleeves.sleeve("ninja_paper").cash_reserved_usd == 0.0
    assert ex.sleeves.sleeve("ninja_paper").cash_available_usd == 2_000.0


def test_fill_through_stop_is_rejected():
    ex = _exec()
    reserved = ex.reserve(
        ticket_id="t1",
        asset_id="btc",
        horizon="daily_swing",
        side="long",
        quantity=0.01,
        reserved_usd=1_000,
        signal_key="btc-stop",
    )
    ex.submit(reserved["order_intent_id"])
    out = ex.fill(
        reserved["order_intent_id"],
        bid=99_000,
        ask=99_100,
        mark=99_050,
        hard_stop=100_000,
    )
    assert out["ok"] is False
    assert out["error"] == "market_changed"
    assert "btc-stop" not in ex.consumed_signals


def test_stale_submit_cancels_without_consuming_signal():
    clock = {"t": 0.0}

    def mono():
        return clock["t"]

    ex = TwoPhaseExecutor(
        SleeveBook.seed(10_000),
        submit_timeout_ms=1_000,
        clock=mono,
    )
    reserved = ex.reserve(
        ticket_id="t1",
        asset_id="pltr",
        horizon="scalp",
        side="long",
        quantity=10,
        reserved_usd=400,
        signal_key="pltr-1",
    )
    ex.submit(reserved["order_intent_id"])
    clock["t"] = 2.0
    expired = ex.expire_stale()
    assert expired[0]["state"] == "CANCELLED_STALE"
    assert "pltr-1" not in ex.consumed_signals
    assert ex.sleeves.sleeve("ibkr_paper").cash_reserved_usd == 0.0


def test_idempotency_key_is_stable():
    a = idempotency_key("t", "long", 1.0, "btc", "swing", "s")
    b = idempotency_key("t", "long", 1.0, "btc", "swing", "s")
    c = idempotency_key("t", "long", 2.0, "btc", "swing", "s")
    assert a == b
    assert a != c
