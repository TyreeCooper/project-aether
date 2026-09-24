from app.order_intent import TwoPhaseExecutor
from app.paper_portfolio import PaperPortfolio
from app.sleeves import sleeve_for_asset


def test_open_position_spends_only_target_sleeve():
    p = PaperPortfolio(10_000)
    opened = p.open_position("nvda", side="long", quantity=10, price=100)
    assert opened["ok"] is True
    assert opened["sleeve_id"] == "ibkr_paper"
    assert p.sleeve_cash("nvda") < 1_000.0
    assert p.sleeve_cash("btc") == 4_000.0
    assert p.can_buy_asset("pltr", 1_001) is False
    assert p.can_buy_asset("btc", 1_001) is True


def test_close_position_returns_cash_to_same_sleeve():
    p = PaperPortfolio(20_000)
    p.open_position("mes", side="long", quantity=1, price=5_000.0)
    before_other = p.sleeve_cash("btc")
    closed = p.close_position("mes", price=5_002.0)
    assert closed["ok"] is True
    assert p.sleeves.sleeve("ninja_paper").realized_pnl_usd != 0.0
    assert p.sleeve_cash("btc") == before_other


def test_two_phase_fill_then_portfolio_does_not_double_debit():
    p = PaperPortfolio(10_000)
    ex = TwoPhaseExecutor(p.sleeves)
    reserved = ex.reserve(
        ticket_id="nvda:intraday",
        asset_id="nvda",
        horizon="intraday",
        side="long",
        quantity=10,
        reserved_usd=1_200,
        signal_key="sig-nvda-1",
    )
    assert reserved["ok"]
    assert p.sleeves.sleeve("ibkr_paper").cash_reserved_usd == 1_200
    submitted = ex.submit(reserved["order_intent_id"])
    assert submitted["state"] == "SUBMITTED"
    filled = ex.fill(
        reserved["order_intent_id"],
        bid=99.0,
        ask=100.0,
        mark=99.5,
    )
    assert filled["ok"]
    opened = p.apply_filled_intent(filled, price=filled["fill_price"])
    assert opened["ok"] is True
    assert p.qty("nvda", position_key="nvda:intraday") == 10
    assert p.sleeves.sleeve("ibkr_paper").cash_reserved_usd == 0.0
    assert p.sleeve_cash("btc") == 4_000.0
    assert p.usd < 10_000


def test_reject_does_not_open_inventory():
    p = PaperPortfolio(10_000)
    ex = TwoPhaseExecutor(p.sleeves)
    reserved = ex.reserve(
        ticket_id="t1",
        asset_id="eurusd",
        horizon="intraday",
        side="long",
        quantity=10_000,
        reserved_usd=700,
        signal_key="fx-reject",
    )
    ex.submit(reserved["order_intent_id"])
    out = ex.reject(reserved["order_intent_id"], "market_changed")
    assert out["state"] == "REJECTED"
    assert p.positions == {}
    assert p.sleeve_cash("eurusd") == 2_000.0


def test_payload_round_trip_keeps_sleeve_split():
    p = PaperPortfolio(10_000)
    p.open_position("btc", side="long", quantity=0.01, price=100_000)
    restored = PaperPortfolio(10_000)
    restored.restore(p.payload())
    assert restored.sleeves.sleeve("kraken_paper").cash_available_usd == p.sleeve_cash("btc")
    assert sleeve_for_asset("btc") == "kraken_paper"
    assert restored.qty("btc") == 0.01
