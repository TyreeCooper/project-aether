import math

from app.fill_model import (
    SLIPPAGE_BPS,
    market_reference_price,
    modeled_fill_price,
    quote_reference_price,
)
from app.pair_book import COST_EDGE_MULTIPLE, PairBook
from app.paper_portfolio import PaperPortfolio


EQUITY = {
    "id": "nvda",
    "name": "NVIDIA",
    "symbol": "NVDA",
    "pair": "NVDA/USD",
    "broker": "interactive_brokers",
}
FUTURE = {
    "id": "mes",
    "name": "Micro E-mini S&P",
    "symbol": "MES",
    "pair": "MES",
    "broker": "ninjatrader",
}


def test_reference_quote_and_fill_prices_are_distinct_and_deterministic():
    bid = 99.90
    ask = 100.10
    mark = 100.00

    assert market_reference_price(
        bid=bid,
        ask=ask,
        mark=mark,
    ) == 100.0
    assert quote_reference_price(
        "buy",
        bid=bid,
        ask=ask,
        mark=mark,
    ) == ask
    assert quote_reference_price(
        "sell",
        bid=bid,
        ask=ask,
        mark=mark,
    ) == bid

    buy = modeled_fill_price(
        "buy",
        bid=bid,
        ask=ask,
        mark=mark,
    )
    sell = modeled_fill_price(
        "sell",
        bid=bid,
        ask=ask,
        mark=mark,
    )
    assert math.isclose(
        buy,
        ask * (1 + SLIPPAGE_BPS / 10_000),
    )
    assert math.isclose(
        sell,
        bid * (1 - SLIPPAGE_BPS / 10_000),
    )


def test_instrument_aware_round_trip_cost_uses_actual_equity_quantity():
    portfolio = PaperPortfolio(300_000.0)
    estimate = portfolio.round_trip_cost_estimate(
        "nvda",
        position_side="long",
        quantity=100.0,
        bid=99.90,
        ask=100.10,
        mark=100.0,
    )

    assert estimate["ok"] is True
    assert estimate["entry"]["fee_usd"] == 1.0
    assert estimate["exit"]["fee_usd"] > 1.0
    assert estimate["spread_usd"] > 0
    assert estimate["slippage_usd"] > 0
    assert math.isclose(
        estimate["total_cost_usd"],
        estimate["spread_usd"]
        + estimate["slippage_usd"]
        + estimate["fees_usd"],
        abs_tol=1e-9,
    )


def test_future_cost_uses_per_contract_fee_and_point_value_for_friction():
    portfolio = PaperPortfolio(300_000.0)
    estimate = portfolio.round_trip_cost_estimate(
        "mes",
        position_side="long",
        quantity=1.0,
        bid=5999.75,
        ask=6000.25,
        mark=6000.0,
    )

    assert estimate["ok"] is True
    assert estimate["entry"]["fee_usd"] == 0.65
    assert estimate["exit"]["fee_usd"] == 0.65
    assert estimate["spread_usd"] == 2.5
    assert estimate["slippage_usd"] > 0


def test_fx_observed_spread_is_not_double_charged_as_fee():
    portfolio = PaperPortfolio(300_000.0)
    estimate = portfolio.round_trip_cost_estimate(
        "eurusd",
        position_side="long",
        quantity=100_000.0,
        bid=1.0999,
        ask=1.1001,
        mark=1.10,
    )

    assert estimate["ok"] is True
    assert estimate["fees_usd"] == 0.0
    assert estimate["spread_usd"] > 0.0
    assert estimate["slippage_usd"] > 0.0


def test_entry_plan_rejects_weak_edge_after_actual_quantity_costing():
    wallet = PaperPortfolio(300_000.0)
    book = PairBook(EQUITY, wallet)
    book.mark = 100.0
    book.bid = 99.0
    book.ask = 101.0

    plan = book.entry_plan(
        2_250.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 2.0,
            "position_key": "nvda:scalp",
            "opportunity_pct": 1.0,
        },
        max_capital_usd=24_000.0,
    )

    assert plan["ok"] is False
    assert plan["error"] == "edge_below_cost_hurdle"
    assert plan["modeled_round_trip_cost_pct"] > 0
    assert math.isclose(
        plan["cost_hurdle_pct"],
        plan["modeled_round_trip_cost_pct"]
        * COST_EDGE_MULTIPLE,
    )
    assert (
        plan["opportunity_pct"]
        < plan["cost_hurdle_pct"]
    )


def test_entry_plan_accepts_edge_that_clears_same_cost_model():
    wallet = PaperPortfolio(300_000.0)
    book = PairBook(EQUITY, wallet)
    book.mark = 100.0
    book.bid = 99.95
    book.ask = 100.05

    plan = book.entry_plan(
        2_250.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 2.0,
            "position_key": "nvda:scalp",
            "opportunity_pct": 5.0,
        },
        max_capital_usd=24_000.0,
    )

    assert plan["ok"] is True
    assert (
        plan["opportunity_pct"]
        >= plan["cost_hurdle_pct"]
    )


def test_closed_trade_costs_reconcile_without_double_charging():
    wallet = PaperPortfolio(300_000.0)
    book = PairBook(EQUITY, wallet)
    book.position_key = "nvda:intraday"
    book.routing_horizon = "intraday"
    book.mark = 100.0
    book.bid = 99.90
    book.ask = 100.10

    entry = book.enter(
        2_250.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "intraday",
            "risk_stop_pct": 2.0,
            "position_key": "nvda:intraday",
            "routing_horizon": "intraday",
            "opportunity_pct": 5.0,
        },
        max_capital_usd=24_000.0,
    )
    assert entry["ok"] is True

    book.mark = 103.0
    book.bid = 102.90
    book.ask = 103.10
    book.stop = 102.0
    book.highest = 104.0

    book.snapshot_strategy = lambda **_kwargs: {
        "risk_stop_pct": 2.0,
        "cost_pct": 0.0,
        "exit_signal": "exit",
    }
    closed = book.manage()

    assert closed is not None
    assert closed["ok"] is True
    assert (
        closed["reference_return_pct"]
        >= closed["gross_return_pct"]
    )
    assert (
        closed["gross_return_pct"]
        >= closed["net_return_pct"]
    )
    assert closed["spread_usd"] > 0
    assert closed["slippage_usd"] > 0
    assert closed["fees_usd"] > 0
    assert closed["total_cost_drag_usd"] > 0
    assert abs(closed["cost_reconciliation_usd"]) < 1e-6
    assert math.isclose(
        closed["cost_drag_pct"],
        closed["spread_drag_pct"]
        + closed["slippage_drag_pct"]
        + closed["fee_drag_pct"],
        abs_tol=0.001,
    )


def test_short_trade_costs_reconcile_with_opposite_execution_sides():
    wallet = PaperPortfolio(300_000.0)
    book = PairBook(FUTURE, wallet)
    book.position_key = "mes:intraday"
    book.routing_horizon = "intraday"
    book.mark = 6000.0
    book.bid = 5999.75
    book.ask = 6000.25

    entry = book.enter(
        1_000.0,
        strategy_snapshot={
            "executable_signal": "short",
            "mode": "intraday",
            "risk_stop_pct": 1.0,
            "position_key": "mes:intraday",
            "routing_horizon": "intraday",
            "opportunity_pct": 5.0,
        },
        max_capital_usd=30_000.0,
    )
    assert entry["ok"] is True
    assert entry["execution_side"] == "sell"

    book.mark = 5980.0
    book.bid = 5979.75
    book.ask = 5980.25
    book.stop = 6010.0
    book.lowest = 5975.0
    book.snapshot_strategy = lambda **_kwargs: {
        "risk_stop_pct": 1.0,
        "cost_pct": 0.0,
        "exit_signal": "exit",
    }

    closed = book.manage()
    assert closed is not None
    assert closed["execution_side"] == "buy"
    assert abs(closed["cost_reconciliation_usd"]) < 1e-6
    assert closed["fees_usd"] == 1.30
