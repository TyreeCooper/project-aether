import math

from app.desk import MultiDesk
from app.paper_portfolio import PaperPortfolio


def _desk(monkeypatch):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.activity_events = []
    desk.opportunity_evaluation_log = []
    for base in desk.books:
        base.wallet = desk.wallet
    for route in desk.route_books.values():
        route.wallet = desk.wallet
    return desk


def test_live_operator_telemetry_distinguishes_strategy_and_validation(monkeypatch):
    desk = _desk(monkeypatch)

    fx_base = desk.by_id["eurusd"]
    fx_base.mark = 1.10
    fx_base.bid = 1.0999
    fx_base.ask = 1.1001
    fx = desk.route_books["eurusd:scalp"]
    opened_strategy = desk.wallet.open_position(
        "eurusd",
        side="long",
        quantity=50_000.0,
        price=1.10,
        stop_price=1.09,
        mode="scalp",
        position_key="eurusd:scalp",
        metadata={
            "routing_horizon": "scalp",
            "originating_horizon": "scalp",
            "entry_reason": "qualified_scalp_grain",
            "quality_score": 91,
            "target_risk_usd": 2_250.0,
        },
    )
    assert opened_strategy["ok"] is True
    fx.stop = 1.09
    fx.entry_at = opened_strategy["opened_at"]
    fx.entry_mode = "scalp"

    mes = desk.by_id["mes"]
    mes.mark = 6000.0
    mes.bid = 5999.75
    mes.ask = 6000.25
    opened_validation = desk.wallet.open_position(
        "mes",
        side="long",
        quantity=1.0,
        price=6000.0,
        stop_price=5900.0,
        mode="execution_test",
        position_key="mes",
        execution_test=True,
        metadata={
            "execution_test": True,
            "execution_test_load": "AETHER-LOAD-002",
            "would_have_blocked_by": "no_setup",
        },
    )
    assert opened_validation["ok"] is True
    mes.stop = 5900.0
    mes.entry_at = opened_validation["opened_at"]
    mes.entry_mode = "execution_test"

    live = desk.live_trades()

    assert live["runtime"]["runtime_release"] == "AETHER-LOAD-003-B8"
    assert live["runtime"]["runtime_mode"] == "strategy_test"
    assert live["runtime"]["forced_entries_enabled"] is False
    assert live["runtime"]["live_blocked"] is True
    assert live["open_count"] == 2
    assert live["strategy_open_count"] == 1
    assert live["execution_validation_open_count"] == 1

    strategy = next(
        row for row in live["items"]
        if row["trade_id"] == opened_strategy["trade_id"]
    )
    validation = next(
        row for row in live["items"]
        if row["trade_id"] == opened_validation["trade_id"]
    )

    assert strategy["trade_class"] == "strategy"
    assert strategy["execution_test"] is False
    assert strategy["position_key"] == "eurusd:scalp"
    assert strategy["originating_horizon"] == "scalp"
    assert strategy["base_units"] == 50_000.0
    assert strategy["standard_lots"] == 0.5
    assert strategy["quantity_unit"] == "EUR units"
    assert strategy["position_risk_usd"] > 0
    assert strategy["position_risk_pct_equity"] > 0

    assert validation["trade_class"] == "execution_validation"
    assert validation["execution_test"] is True
    assert validation["execution_test_load"] == "AETHER-LOAD-002"
    assert validation["contracts"] == 1.0
    assert validation["quantity_unit"] == "contracts"
    assert validation["would_have_blocked_by"] == "no_setup"

    # Strategy risk excludes isolated execution-validation positions.
    expected_fx_risk = desk.wallet.position_stop_risk_usd(
        "eurusd",
        position_key="eurusd:scalp",
    )
    assert math.isclose(
        live["risk"]["open_stop_risk_usd"],
        expected_fx_risk,
        abs_tol=1e-6,
    )
    assert (
        live["risk"]["remaining_portfolio_risk_usd"]
        <= live["risk"]["max_portfolio_risk_usd"]
    )


def test_setup_watch_exposes_latest_route_status_and_gate_reason(monkeypatch):
    desk = _desk(monkeypatch)
    route = desk.route_books["nvda:scalp"]

    row = desk._record_opportunity_evaluation(
        route,
        routing_horizon="scalp",
        clock_horizon_value="scalp",
        strategy_id="scalp-test",
        strategy_version="v1",
        mode="scalp",
        snapshot={
            "signal": "buy",
            "executable_signal": "buy",
            "quality_score": 88,
            "reason": "qualified_scalp_grain",
            "execution_status": "paper_long_ready",
        },
        status="qualified",
    )
    row.update(
        {
            "modeled_round_trip_cost_pct": 0.42,
            "cost_hurdle_pct": 0.588,
        }
    )
    desk._update_opportunity_evaluation(
        row,
        status="blocked",
        rejection_reason="edge_below_cost_hurdle",
    )

    watch = desk.live_trades()["watch"]
    item = next(
        candidate
        for candidate in watch
        if candidate["route_key"] == "nvda:scalp"
    )

    assert item["trade_class"] == "strategy"
    assert item["status"] == "blocked"
    assert item["gate_reason"] == "edge_below_cost_hurdle"
    assert item["reason"] == "edge_below_cost_hurdle"
    assert item["quality_score"] == 88
    assert item["modeled_round_trip_cost_pct"] == 0.42
    assert item["cost_hurdle_pct"] == 0.588
    assert item["actionable"] is False


def test_blotter_operator_rows_keep_trade_class_and_horizon(monkeypatch):
    desk = _desk(monkeypatch)

    strategy = desk.wallet.open_position(
        "nvda",
        side="long",
        quantity=10.0,
        price=100.0,
        stop_price=98.0,
        mode="intraday",
        position_key="nvda:intraday",
        metadata={
            "routing_horizon": "intraday",
            "originating_horizon": "intraday",
        },
    )
    assert strategy["ok"] is True
    closed_strategy = desk.wallet.close_position(
        "nvda",
        price=103.0,
        position_key="nvda:intraday",
        exit_reason="rule_exit",
    )
    assert closed_strategy["ok"] is True
    desk.wallet.annotate_closed_trade(
        strategy["trade_id"],
        {
            "mfe_pct": 4.0,
            "mae_pct": -1.0,
            "capture_efficiency_pct": 62.5,
            "total_cost_drag_usd": 3.25,
        },
    )

    validation = desk.wallet.open_position(
        "mes",
        side="long",
        quantity=1.0,
        price=6000.0,
        stop_price=5900.0,
        mode="execution_test",
        execution_test=True,
        metadata={
            "execution_test": True,
            "execution_test_load": "AETHER-LOAD-002",
        },
    )
    assert validation["ok"] is True
    closed_validation = desk.wallet.close_position(
        "mes",
        price=6001.0,
        exit_reason="execution_test_close",
    )
    assert closed_validation["ok"] is True

    rows = desk.blotter()
    strategy_row = next(
        row for row in rows
        if row["trade_id"] == strategy["trade_id"]
    )
    validation_row = next(
        row for row in rows
        if row["trade_id"] == validation["trade_id"]
    )

    assert strategy_row["trade_class"] == "strategy"
    assert strategy_row["execution_test"] is False
    assert strategy_row["routing_horizon"] == "intraday"
    assert strategy_row["originating_horizon"] == "intraday"
    assert strategy_row["mfe_pct"] == 4.0
    assert strategy_row["mae_pct"] == -1.0
    assert strategy_row["capture_efficiency_pct"] == 62.5
    assert strategy_row["total_cost_drag_usd"] == 3.25

    assert validation_row["trade_class"] == "execution_validation"
    assert validation_row["execution_test"] is True
    assert validation_row["execution_test_funded"] is True


def test_floor_portfolio_exposes_strategy_risk_capacity(monkeypatch):
    desk = _desk(monkeypatch)
    snap = desk.floor_snapshot()
    risk = snap["portfolio"]["strategy_risk"]

    assert "open_stop_risk_usd" in risk
    assert "remaining_portfolio_risk_usd" in risk
    assert "max_portfolio_risk_usd" in risk
    assert risk["max_portfolio_risk_usd"] > 0
