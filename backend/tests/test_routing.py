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
