from app.horizons import TradingHorizon
from app.routing import PaperStrategyRouter, ROUTES


def test_router_releases_enabled_horizons_only():
    router = PaperStrategyRouter()
    due = router.due(3599)
    horizons = {route.horizon for route in due}
    assert TradingHorizon.HFT not in horizons
    assert TradingHorizon.SCALP in horizons
    assert TradingHorizon.INTRADAY in horizons
    assert TradingHorizon.SWING in horizons


def test_router_is_at_most_once_per_closed_bucket():
    router = PaperStrategyRouter()
    first = router.due(299)
    second = router.due(299)
    assert first
    assert second == ()


def test_routes_carry_stable_strategy_attribution():
    route = ROUTES[TradingHorizon.INTRADAY]
    assert route.strategy_id == "trend_breakout"
    assert route.strategy_version == "v3"
    assert route.horizon == TradingHorizon.INTRADAY



def test_desk_scalp_route_reaches_actual_allocator_and_records_attribution(monkeypatch):
    from app.desk import MultiDesk
    from app.paper_portfolio import PaperPortfolio

    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(desk, "_btc_gate", lambda: (True, False))
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: (ROUTES[TradingHorizon.SCALP],),
    )

    scalp_calls = []
    for book in desk.books:
        book.wallet = desk.wallet
        book.mark = 5_000.0 if book.id == "mes" else 100.0
        book.bid = book.mark - 0.1
        book.ask = book.mark + 0.1
        book.bars.clear()
        book.bars.append(
            {
                "ts": 1_700_000_000,
                "open": book.mark,
                "high": book.mark,
                "low": book.mark,
                "close": book.mark,
                "volume": 1.0,
            }
        )

        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            if requested_mode == "scalp":
                scalp_calls.append(_book.id)
            if _book.id == "mes" and requested_mode == "scalp":
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": "scalp",
                    "reason": "qualified_scalp_grain",
                    "execution_status": "paper_long_ready",
                    "quality_score": 100,
                    "risk_stop_pct": 1.0,
                    "signal_key": "scalp:1700000000",
                    "entry_clock": "1m",
                    "bias_clock": "1d/4h/1h",
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }

        book.snapshot_strategy = snapshot_strategy

    out = desk._allocate()
    successful = [row for row in out if row.get("ok")]
    assert len(successful) == 1
    assert successful[0]["pair"] == desk.by_id["mes"].pair

    position = desk.wallet.position("mes")
    assert position is not None
    assert position["mode"] == "scalp"
    assert position["metadata"]["routing_horizon"] == "scalp"
    assert position["metadata"]["clock_horizon"] == "scalp"
    assert position["metadata"]["strategy_id"] == "trend_breakout"
    assert position["metadata"]["strategy_version"] == "v3"

    assert set(scalp_calls) == {
        "eurusd",
        "usdjpy",
        "mes",
        "mnq",
        "nvda",
        "tsla",
        "pltr",
    }
    evaluations = desk.opportunity_evaluations_snapshot(100)
    assert len(evaluations) == 7
    entered = next(
        row for row in evaluations
        if row["asset_id"] == "mes"
    )
    assert entered["status"] == "entered"
    assert entered["routing_horizon"] == "scalp"
    rejected = [
        row for row in evaluations
        if row["asset_id"] != "mes"
    ]
    assert len(rejected) == 6
    assert all(row["status"] == "rejected" for row in rejected)
    assert all(row["rejection_reason"] == "no_setup" for row in rejected)


def test_desk_restores_strategy_route_buckets():
    from app.desk import MultiDesk

    desk = MultiDesk(execution_test_mode=False)
    desk.strategy_router.clock.last_bucket.clear()
    desk._restore(
        {
            "strategy_route_buckets": {
                "scalp": 1_700_000_000,
                "intraday": 1_699_999_800,
            }
        }
    )
    assert (
        desk.strategy_router.clock.last_bucket[TradingHorizon.SCALP]
        == 1_700_000_000
    )
    assert (
        desk.strategy_router.clock.last_bucket[TradingHorizon.INTRADAY]
        == 1_699_999_800
    )

def _prepare_strategy_test_desk(monkeypatch, due_routes):
    from app.desk import MultiDesk
    from app.paper_portfolio import PaperPortfolio

    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(desk, "_btc_gate", lambda: (True, False))
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: tuple(due_routes),
    )
    for book in desk.books:
        book.wallet = desk.wallet
        book.mark = 5_000.0 if book.id == "mes" else 100.0
        book.bid = book.mark - 0.1
        book.ask = book.mark + 0.1
        book.bars.clear()
        book.bars.append(
            {
                "ts": 1_700_000_000,
                "open": book.mark,
                "high": book.mark,
                "low": book.mark,
                "close": book.mark,
                "volume": 1.0,
            }
        )
    return desk


def test_strategy_test_evaluates_all_28_supported_asset_horizon_routes(monkeypatch):
    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (
            ROUTES[TradingHorizon.SCALP],
            ROUTES[TradingHorizon.INTRADAY],
            ROUTES[TradingHorizon.SWING],
            ROUTES[TradingHorizon.POSITION],
        ),
    )
    calls = []

    for book in desk.books:
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            calls.append((_book.id, requested_mode))
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }
        book.snapshot_strategy = snapshot_strategy

    assert desk._allocate() == []

    evaluations = desk.opportunity_evaluations_snapshot(100)
    assert len(evaluations) == 28
    assert sum(row["status"] == "rejected" for row in evaluations) == 28
    assert all(row["rejection_reason"] == "no_setup" for row in evaluations)
    assert all(row["strategy_qualified"] is False for row in evaluations)

    expected = {
        (book.id, mode)
        for book in desk.books
        for mode in (
            "daily_swing"
            if book.id in {"btc", "eth"}
            else None,
        )
        if mode is not None
    }
    expected |= {
        (book.id, horizon)
        for book in desk.books
        for horizon in ("scalp", "intraday", "swing")
        if horizon in __import__(
            "app.execution_matrix",
            fromlist=["supported_horizons"],
        ).supported_horizons(book.id)
        and book.id not in {"btc", "eth"}
    }
    assert set(calls) == expected


def test_rejected_route_preserves_gate_reason(monkeypatch):
    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )
    for book in desk.books:
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "grain_not_aligned",
                "execution_status": "no_trade",
                "quality_score": 40,
            }
        book.snapshot_strategy = snapshot_strategy

    assert desk._allocate() == []
    rows = desk.opportunity_evaluations_snapshot(100)
    assert len(rows) == 7
    assert all(row["status"] == "rejected" for row in rows)
    assert all(row["rejection_reason"] == "grain_not_aligned" for row in rows)
    assert all(row["quality_score"] == 40 for row in rows)


def test_qualified_intraday_route_reaches_paper_entry(monkeypatch):
    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.INTRADAY],),
    )
    for book in desk.books:
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            if _book.id == "mes" and requested_mode == "intraday":
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": "intraday",
                    "reason": "qualified_intraday_grain",
                    "execution_status": "paper_long_ready",
                    "quality_score": 95,
                    "risk_stop_pct": 1.0,
                    "signal_key": "intraday:1700000000",
                    "entry_clock": "15m",
                    "bias_clock": "1d/4h",
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }
        book.snapshot_strategy = snapshot_strategy

    out = desk._allocate()
    assert sum(bool(row.get("ok")) for row in out) == 1
    position = desk.wallet.position("mes")
    assert position is not None
    assert position["mode"] == "intraday"
    row = next(
        item
        for item in desk.opportunity_evaluations_snapshot(100)
        if item["asset_id"] == "mes"
    )
    assert row["status"] == "entered"
    assert row["routing_horizon"] == "intraday"
    assert row["trade_id"] == position["trade_id"]


def test_qualified_swing_route_reaches_paper_entry(monkeypatch):
    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SWING],),
    )
    for book in desk.books:
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            if _book.id == "mcl" and requested_mode == "swing":
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": "swing",
                    "reason": "qualified_swing_grain",
                    "execution_status": "paper_long_ready",
                    "quality_score": 93,
                    "risk_stop_pct": 2.0,
                    "signal_key": "swing:1700000000",
                    "entry_clock": "1h",
                    "bias_clock": "1d/4h",
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }
        book.snapshot_strategy = snapshot_strategy

    out = desk._allocate()
    assert sum(bool(row.get("ok")) for row in out) == 1
    position = desk.wallet.position("mcl")
    assert position is not None
    assert position["mode"] == "swing"
    row = next(
        item
        for item in desk.opportunity_evaluations_snapshot(100)
        if item["asset_id"] == "mcl"
    )
    assert row["status"] == "entered"
    assert row["routing_horizon"] == "swing"


def test_qualified_short_route_preserves_supported_direction(monkeypatch):
    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )
    for book in desk.books:
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=book,
        ):
            if _book.id == "mes" and requested_mode == "scalp":
                return {
                    "signal": "short",
                    "executable_signal": "short",
                    "mode": "scalp",
                    "reason": "qualified_scalp_grain",
                    "execution_status": "paper_short_ready",
                    "quality_score": 99,
                    "risk_stop_pct": 1.0,
                    "signal_key": "scalp:short:1700000000",
                    "entry_clock": "1m",
                    "bias_clock": "1d/4h/1h",
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }
        book.snapshot_strategy = snapshot_strategy

    out = desk._allocate()
    assert sum(bool(row.get("ok")) for row in out) == 1
    position = desk.wallet.position("mes")
    assert position is not None
    assert position["side"] == "short"


def test_execution_validation_override_cannot_leak_into_strategy_mode(monkeypatch):
    import app.desk as desk_module

    desk = _prepare_strategy_test_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )

    def forbidden_override(*_args, **_kwargs):
        raise AssertionError("forced execution override leaked into strategy mode")

    monkeypatch.setattr(
        desk_module,
        "forced_execution_snapshot",
        forbidden_override,
    )
    for book in desk.books:
        book.snapshot_strategy = lambda **_kwargs: {
            "signal": None,
            "executable_signal": None,
            "mode": "scalp",
            "reason": "no_setup",
            "execution_status": "no_trade",
            "quality_score": 0,
        }

    assert desk._allocate() == []
    assert desk.wallet.positions == {}


def test_opportunity_evaluations_survive_restore():
    from app.desk import MultiDesk

    desk = MultiDesk(execution_test_mode=False)
    desk._restore(
        {
            "opportunity_evaluations": [
                {
                    "evaluation_id": "eval-1",
                    "asset_id": "mes",
                    "routing_horizon": "scalp",
                    "status": "rejected",
                    "rejection_reason": "no_1m_continuation",
                    "ts": "2026-09-23T12:00:00+00:00",
                }
            ]
        }
    )
    rows = desk.opportunity_evaluations_snapshot()
    assert rows[0]["evaluation_id"] == "eval-1"
    assert rows[0]["rejection_reason"] == "no_1m_continuation"

