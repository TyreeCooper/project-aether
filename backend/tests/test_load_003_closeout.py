import asyncio
import math

from app import desk as desk_module
from app import live
from app.desk import (
    PORTFOLIO_RISK_FRACTION,
    TRADE_RISK_FRACTION,
    MultiDesk,
)
from app.horizons import TradingHorizon
from app.paper_portfolio import (
    PaperPortfolio,
    strategy_position_key,
)
from app.routing import ROUTES


MARKS = {
    "eurusd": 1.10,
    "usdjpy": 150.0,
    "mes": 6000.0,
    "mnq": 21000.0,
    "mgc": 3000.0,
    "mcl": 70.0,
    "us10y": 110.0,
    "nvda": 180.0,
    "tsla": 450.0,
    "pltr": 180.0,
    "btc": 100000.0,
    "eth": 4000.0,
}


def _strategy_desk(monkeypatch, due_routes=()):
    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: None,
    )
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(
        desk,
        "_btc_gate",
        lambda: (True, False),
    )
    monkeypatch.setattr(
        desk,
        "_latest_closed_minute_ts",
        lambda: 1_700_000_060,
    )
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: tuple(due_routes),
    )
    for base in desk.books:
        base.wallet = desk.wallet
        base.mark = MARKS[base.id]
        spread = max(base.mark * 0.0001, 0.0001)
        base.bid = base.mark - spread
        base.ask = base.mark + spread
        base.bars.clear()
        base.bars.append(
            {
                "ts": 1_700_000_000,
                "open": base.mark,
                "high": base.mark,
                "low": base.mark,
                "close": base.mark,
                "volume": 1.0,
            }
        )
        desk._sync_asset_route_books(base.id)
    for route in desk.route_books.values():
        route.wallet = desk.wallet
    return desk


def _qualify_only(desk, eligible, *, stop_pct=1.0):
    eligible = set(eligible)
    ordered = sorted(eligible)
    for route in desk.route_books.values():

        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=route,
        ):
            key = (
                _book.id,
                _book.routing_horizon,
            )
            if key in eligible:
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": requested_mode,
                    "reason": "b9_qualified",
                    "execution_status": "paper_long_ready",
                    "quality_score": 100 - ordered.index(key),
                    "risk_stop_pct": stop_pct,
                    "signal_key": (
                        f"b9:{_book.id}:"
                        f"{_book.routing_horizon}"
                    ),
                    "entry_clock": "test",
                    "bias_clock": "test",
                    "opportunity_pct": 10.0,
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }

        route.snapshot_strategy = snapshot_strategy


def test_b9_runtime_contract_keeps_strategy_test_paper_and_validation_isolated(
    monkeypatch,
):
    strategy = _strategy_desk(monkeypatch)
    status = strategy.engine_status()
    settings = strategy.settings_snapshot()

    assert status["runtime_release"] == "AETHER-LOAD-003-B9"
    assert status["runtime_mode"] == "strategy_test"
    assert status["strategy_test_mode"] is True
    assert status["execution_validation_mode"] is False
    assert status["forced_entries_enabled"] is False
    assert status["paper_mode"] is True
    assert status["live_blocked"] is True
    assert strategy.armed is True

    assert settings["strategy_risk_policy"] == {
        "max_trade_risk_pct": 0.75,
        "max_asset_risk_pct": 1.5,
        "max_cluster_risk_pct": 2.25,
        "max_portfolio_risk_pct": 3.0,
        "fixed_strategy_position_limit": None,
    }
    assert settings["instrument_sizing_policy"] == {
        "fx_max_standard_lots": 1.0,
        "fx_max_base_units": 100000.0,
        "micro_future_max_contracts": 1.0,
        "equity_quantity_unit": "shares",
        "crypto_quantity_unit": "coin_quantity",
    }

    validation = MultiDesk(execution_test_mode=True)
    validation_status = validation.engine_status()
    assert validation_status["runtime_mode"] == "execution_validation"
    assert validation_status["execution_validation_mode"] is True
    assert validation_status["forced_entries_enabled"] is True
    assert validation_status["live_blocked"] is True


def test_b9_all_supported_routes_reject_zero_signal_even_with_bullish_intelligence(
    monkeypatch,
):
    due = (
        ROUTES[TradingHorizon.SCALP],
        ROUTES[TradingHorizon.INTRADAY],
        ROUTES[TradingHorizon.SWING],
        ROUTES[TradingHorizon.POSITION],
    )
    desk = _strategy_desk(monkeypatch, due)

    # Deliberately extreme context. These feeds remain shadow-only and
    # must not manufacture a strategy signal or paper order.
    desk.community_cache["nvda"] = {
        "sentiment": 100.0,
        "claims_verified": False,
        "trade_influence_enabled": False,
    }
    desk.news_cache["nvda"] = {
        "sentiment": 100.0,
        "shadow_only": True,
        "trade_influence_enabled": False,
    }
    desk.crypto_events = [
        {
            "title": "extreme bullish test event",
            "trade_influence_enabled": False,
        }
    ]

    calls = []
    for route in desk.route_books.values():

        def no_signal(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=route,
        ):
            calls.append(
                (_book.id, _book.routing_horizon)
            )
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }

        route.snapshot_strategy = no_signal

    assert desk._allocate() == []
    assert desk.wallet.positions == {}

    evaluations = desk.opportunity_evaluations_snapshot(100)
    assert len(evaluations) == 28
    assert len(calls) == 28
    assert all(
        row["status"] == "rejected"
        for row in evaluations
    )
    assert all(
        row["rejection_reason"] == "no_setup"
        for row in evaluations
    )
    assert all(
        row["strategy_qualified"] is False
        for row in evaluations
    )


def test_b9_multi_horizon_persistence_duplicate_block_and_sibling_isolation(
    monkeypatch,
):
    saved = []
    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: None,
    )
    monkeypatch.setattr(
        desk_module,
        "save_desk",
        lambda payload: saved.append(payload),
    )
    source = MultiDesk(execution_test_mode=False)
    source.wallet = PaperPortfolio(300_000.0)
    for route in source.route_books.values():
        route.wallet = source.wallet

    scalp_key = strategy_position_key("nvda", "scalp")
    swing_key = strategy_position_key("nvda", "swing")
    opened = {}
    for key, horizon, stop, high, low in (
        (scalp_key, "scalp", 175.0, 184.0, 178.0),
        (swing_key, "swing", 165.0, 192.0, 170.0),
    ):
        row = source.wallet.open_position(
            "nvda",
            side="long",
            quantity=10.0,
            price=180.0,
            stop_price=stop,
            mode=horizon,
            position_key=key,
            metadata={
                "routing_horizon": horizon,
                "originating_horizon": horizon,
                "management_mode": horizon,
            },
        )
        assert row["ok"] is True
        opened[key] = row
        route = source.route_books[key]
        route.stop = stop
        route.highest = high
        route.lowest = low
        route.entry_at = row["opened_at"]
        route.entry_mode = horizon

    source.persist()
    assert saved
    persisted = saved[-1]

    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: persisted,
    )
    restored = MultiDesk(execution_test_mode=False)

    assert set(restored.wallet.positions) >= {
        scalp_key,
        swing_key,
    }
    assert restored.route_books[scalp_key].stop == 175.0
    assert restored.route_books[swing_key].stop == 165.0
    assert (
        restored.route_books[scalp_key]
        .management_contract(
            restored.wallet.position(
                "nvda",
                position_key=scalp_key,
            )
        )["originating_horizon"]
        == "scalp"
    )
    assert (
        restored.route_books[swing_key]
        .management_contract(
            restored.wallet.position(
                "nvda",
                position_key=swing_key,
            )
        )["originating_horizon"]
        == "swing"
    )

    duplicate = restored.wallet.open_position(
        "nvda",
        side="long",
        quantity=1.0,
        price=180.0,
        stop_price=175.0,
        mode="scalp",
        position_key=scalp_key,
    )
    assert duplicate["ok"] is False
    assert duplicate["error"] == "position_already_open"

    closed = restored.wallet.close_position(
        "nvda",
        price=182.0,
        position_key=scalp_key,
        exit_reason="b9_sibling_close",
    )
    assert closed["ok"] is True
    assert restored.wallet.position(
        "nvda",
        position_key=scalp_key,
    ) is None
    sibling = restored.wallet.position(
        "nvda",
        position_key=swing_key,
    )
    assert sibling is not None
    assert sibling["trade_id"] == opened[swing_key]["trade_id"]


def test_b9_portfolio_risk_exhaustion_then_close_restores_entry_capacity(
    monkeypatch,
):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SWING],),
    )
    trade_risk = 300_000.0 * TRADE_RISK_FRACTION

    seeded = []
    for index, aid in enumerate(
        ("nvda", "tsla", "pltr", "eurusd")
    ):
        entry = MARKS[aid]
        qty = 10_000.0 if aid == "eurusd" else 100.0
        distance = trade_risk / qty
        row = desk.wallet.open_position(
            aid,
            side="long",
            quantity=qty,
            price=entry,
            stop_price=entry - distance,
            mode="swing",
            position_key=f"{aid}:b9-seed-{index}",
            metadata={
                "cluster": (
                    "fx"
                    if aid == "eurusd"
                    else "us_equity_beta"
                ),
                "routing_horizon": "swing",
            },
            test_allow_sleeve_overflow=True,
        )
        assert row["ok"] is True
        seeded.append(row)

    _qualify_only(
        desk,
        {("mcl", "swing")},
        stop_pct=1.0,
    )
    blocked = desk._allocate()
    assert not any(row.get("ok") for row in blocked)
    first_eval = next(
        row
        for row in desk.opportunity_evaluations_snapshot(100)
        if row["asset_id"] == "mcl"
        and row["routing_horizon"] == "swing"
    )
    assert (
        first_eval["rejection_reason"]
        == "aggregate_open_risk_limit"
    )

    full = desk.strategy_risk_snapshot(300_000.0)
    assert math.isclose(
        full["open_stop_risk_usd"],
        300_000.0 * PORTFOLIO_RISK_FRACTION,
        abs_tol=1e-6,
    )
    assert full["remaining_portfolio_risk_usd"] == 0.0

    released = desk.wallet.close_position(
        "eurusd",
        price=MARKS["eurusd"],
        position_key="eurusd:b9-seed-3",
        exit_reason="b9_risk_release",
    )
    assert released["ok"] is True

    recovered = desk.strategy_risk_snapshot()
    assert recovered["remaining_portfolio_risk_usd"] > 0.0

    desk.opportunity_evaluation_log = []
    entered = desk._allocate()
    success = [
        row
        for row in entered
        if row.get("ok")
        and row.get("asset_id") == "mcl"
    ]
    assert len(success) == 1
    final_risk = desk.strategy_risk_snapshot()
    assert (
        final_risk["open_stop_risk_usd"]
        <= final_risk["max_portfolio_risk_usd"]
        + 1e-6
    )


def test_b9_allocator_still_allows_more_than_four_low_risk_positions(
    monkeypatch,
):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )
    desk.risk_slice = 0.01
    eligible = {
        ("eurusd", "scalp"),
        ("usdjpy", "scalp"),
        ("mes", "scalp"),
        ("mnq", "scalp"),
        ("nvda", "scalp"),
        ("tsla", "scalp"),
        ("pltr", "scalp"),
    }
    _qualify_only(
        desk,
        eligible,
        stop_pct=0.25,
    )

    successful = [
        row
        for row in desk._allocate()
        if row.get("ok")
    ]
    assert len(successful) > 4
    risk = desk.strategy_risk_snapshot()
    assert (
        risk["open_stop_risk_usd"]
        <= risk["max_portfolio_risk_usd"] + 1e-6
    )
    assert desk.wallet.test_overflow_usd == 0.0


def test_b9_legacy_execution_validation_retires_before_allocator(
    monkeypatch,
):
    desk = _strategy_desk(monkeypatch)
    btc = desk.by_id["btc"]
    btc.mark = 100_000.0

    opened = desk.wallet.open_position(
        "btc",
        side="long",
        quantity=0.0001,
        price=100_000.0,
        stop_price=90_000.0,
        mode="execution_test",
        position_key="btc",
        execution_test=True,
        metadata={
            "execution_test": True,
            "execution_test_load": "AETHER-LOAD-002",
        },
    )
    assert opened["ok"] is True
    btc.entry_at = opened["opened_at"]
    btc.entry_mode = "execution_test"
    btc.stop = 90_000.0

    async def noop():
        return None

    for name in (
        "_refresh_risk_calendar",
        "_refresh_crypto_calendar",
        "_refresh_one_community",
        "_refresh_one_news",
        "_quotes",
        "_refresh_context_bars",
        "_persist_intelligence",
    ):
        monkeypatch.setattr(desk, name, noop)

    allocator_calls = []
    monkeypatch.setattr(
        desk,
        "_allocate",
        lambda: allocator_calls.append(True) or [],
    )

    asyncio.run(desk.tick())

    assert allocator_calls == []
    assert desk.wallet.position(
        "btc",
        position_key="btc",
    ) is None
    retired = next(
        row
        for row in desk.wallet.closed_trades
        if row["trade_id"] == opened["trade_id"]
    )
    assert retired["exit_reason"] == "execution_test_retired"
    assert retired["execution_test_funded"] is True
    assert any(
        event.get("exit_reason")
        == "execution_test_retired"
        for event in desk.activity_events
    )


def test_b9_instrument_caps_and_live_order_boundary_remain_hard(
    monkeypatch,
):
    fx = PaperPortfolio(300_000.0)
    fx_open = fx.open_position(
        "eurusd",
        side="long",
        quantity=250_000.0,
        price=1.10,
        stop_price=1.09,
    )
    assert fx_open["ok"] is True
    assert fx_open["base_units"] == 100_000.0
    assert fx_open["standard_lots"] == 1.0

    future = PaperPortfolio(300_000.0)
    future_open = future.open_position(
        "mes",
        side="long",
        quantity=5.0,
        price=6000.0,
        stop_price=5900.0,
    )
    assert future_open["ok"] is True
    assert future_open["contracts"] == 1.0

    equity = PaperPortfolio(300_000.0)
    equity_open = equity.open_position(
        "nvda",
        side="long",
        quantity=10.0,
        price=180.0,
        stop_price=175.0,
    )
    assert equity_open["ok"] is True
    assert equity_open["shares"] == 10.0

    crypto = PaperPortfolio(300_000.0)
    crypto_open = crypto.open_position(
        "btc",
        side="long",
        quantity=2.0,
        price=100_000.0,
        stop_price=95_000.0,
        test_allow_sleeve_overflow=True,
    )
    assert crypto_open["ok"] is True
    assert crypto_open["coin_quantity"] == 2.0

    monkeypatch.setenv("AETHER_LIVE", "1")
    monkeypatch.setenv("KRAKEN_API_KEY", "test-key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "test-secret")
    result = asyncio.run(
        live.place_order(
            pair="XBTUSD",
            side="buy",
            volume=0.0001,
        )
    )
    assert result["ok"] is False
    assert result["error"] == "live_orders_blocked"
    assert result["orders_enabled"] is False
