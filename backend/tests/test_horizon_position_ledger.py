from app.desk import MultiDesk
from app.horizons import TradingHorizon
from app.paper_portfolio import PaperPortfolio, strategy_position_key
from app.routing import ROUTES


def test_portfolio_allows_two_horizons_for_same_asset_and_closes_independently():
    portfolio = PaperPortfolio(300_000.0)
    scalp_key = strategy_position_key("nvda", "scalp")
    swing_key = strategy_position_key("nvda", "swing")

    scalp = portfolio.open_position(
        "nvda",
        side="long",
        quantity=10,
        price=100.0,
        stop_price=99.0,
        mode="scalp",
        position_key=scalp_key,
        metadata={"routing_horizon": "scalp"},
    )
    swing = portfolio.open_position(
        "nvda",
        side="long",
        quantity=5,
        price=101.0,
        stop_price=96.0,
        mode="swing",
        position_key=swing_key,
        metadata={"routing_horizon": "swing"},
    )

    assert scalp["ok"] is True
    assert swing["ok"] is True
    assert set(portfolio.positions) == {scalp_key, swing_key}
    assert portfolio.position("nvda") is None
    assert portfolio.position(
        "nvda",
        position_key=scalp_key,
    )["trade_id"] == scalp["trade_id"]
    assert portfolio.position(
        "nvda",
        position_key=swing_key,
    )["trade_id"] == swing["trade_id"]

    closed = portfolio.close_position(
        "nvda",
        price=102.0,
        exit_reason="test_close",
        position_key=scalp_key,
    )
    assert closed["ok"] is True
    assert portfolio.position(
        "nvda",
        position_key=scalp_key,
    ) is None
    survivor = portfolio.position(
        "nvda",
        position_key=swing_key,
    )
    assert survivor is not None
    assert survivor["trade_id"] == swing["trade_id"]


def test_portfolio_rejects_duplicate_same_asset_horizon_route():
    portfolio = PaperPortfolio(300_000.0)
    key = strategy_position_key("mes", "intraday")
    first = portfolio.open_position(
        "mes",
        side="long",
        quantity=1,
        price=5_000.0,
        stop_price=4_990.0,
        mode="intraday",
        position_key=key,
    )
    second = portfolio.open_position(
        "mes",
        side="long",
        quantity=1,
        price=5_001.0,
        stop_price=4_991.0,
        mode="intraday",
        position_key=key,
    )
    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"] == "position_already_open"
    assert second["position_key"] == key


def test_horizon_position_keys_survive_portfolio_restore():
    source = PaperPortfolio(300_000.0)
    keys = [
        strategy_position_key("nvda", "scalp"),
        strategy_position_key("nvda", "swing"),
    ]
    opened = []
    for index, key in enumerate(keys):
        horizon = key.split(":", 1)[1]
        opened.append(
            source.open_position(
                "nvda",
                side="long",
                quantity=1 + index,
                price=100.0 + index,
                stop_price=95.0,
                mode=horizon,
                position_key=key,
                metadata={"routing_horizon": horizon},
            )
        )
    restored = PaperPortfolio(300_000.0)
    restored.restore(source.payload())

    assert set(restored.positions) == set(keys)
    for key, original in zip(keys, opened):
        row = restored.position("nvda", position_key=key)
        assert row is not None
        assert row["trade_id"] == original["trade_id"]
        assert row["position_key"] == key


def test_desk_migrates_legacy_strategy_position_to_horizon_key(monkeypatch):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = MultiDesk(execution_test_mode=False)
    payload = {
        "starting_usd": 300_000.0,
        "usd": 299_000.0,
        "positions": {
            "nvda": {
                "trade_id": "legacy-route-trade",
                "asset_id": "nvda",
                "product_type": "equity",
                "side": "long",
                "quantity": 1.0,
                "quantity_unit": "shares",
                "entry_price": 100.0,
                "entry_reference_price": 100.0,
                "entry_fee_usd": 0.0,
                "margin_reserved_usd": 100.0,
                "opened_at": "2026-09-23T12:00:00+00:00",
                "mode": "intraday",
                "signal_key": "intraday:1",
                "initial_stop": 95.0,
                "current_stop": 95.0,
                "metadata": {},
                "execution_test_funded": False,
            }
        },
        "closed_trades": [],
    }
    desk._restore({"wallet": payload, "books": {}})

    key = strategy_position_key("nvda", "intraday")
    assert "nvda" not in desk.wallet.positions
    row = desk.wallet.position("nvda", position_key=key)
    assert row is not None
    assert row["trade_id"] == "legacy-route-trade"
    assert row["legacy_position_key_migrated"] is True
    assert row["metadata"]["routing_horizon"] == "intraday"


def _prepare_multi_horizon_desk(monkeypatch):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(desk, "_btc_gate", lambda: (True, False))
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: (
            ROUTES[TradingHorizon.SCALP],
            ROUTES[TradingHorizon.INTRADAY],
        ),
    )
    for base in desk.books:
        base.wallet = desk.wallet
        base.mark = 5_000.0 if base.id == "mes" else 100.0
        base.bid = base.mark - 0.1
        base.ask = base.mark + 0.1
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
    for route_book in desk.route_books.values():
        route_book.wallet = desk.wallet
    return desk


def test_allocator_can_open_two_horizons_for_same_asset(monkeypatch):
    desk = _prepare_multi_horizon_desk(monkeypatch)

    for route_book in desk.route_books.values():
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=route_book,
        ):
            horizon = _book.routing_horizon
            if _book.id == "mes" and horizon in {"scalp", "intraday"}:
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": requested_mode,
                    "reason": f"qualified_{horizon}",
                    "execution_status": "paper_long_ready",
                    "quality_score": 100 if horizon == "scalp" else 99,
                    "risk_stop_pct": 1.0,
                    "signal_key": f"{horizon}:1700000000",
                    "entry_clock": (
                        "1m" if horizon == "scalp" else "15m"
                    ),
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
        route_book.snapshot_strategy = snapshot_strategy

    out = desk._allocate()
    successful = [row for row in out if row.get("ok")]
    assert len(successful) == 2

    scalp_key = strategy_position_key("mes", "scalp")
    intraday_key = strategy_position_key("mes", "intraday")
    scalp = desk.wallet.position("mes", position_key=scalp_key)
    intraday = desk.wallet.position(
        "mes",
        position_key=intraday_key,
    )
    assert scalp is not None
    assert intraday is not None
    assert scalp["trade_id"] != intraday["trade_id"]
    assert scalp["metadata"]["routing_horizon"] == "scalp"
    assert intraday["metadata"]["routing_horizon"] == "intraday"


def test_route_book_state_restores_without_cross_horizon_corruption(monkeypatch):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    source = MultiDesk(execution_test_mode=False)
    source.wallet = PaperPortfolio(300_000.0)
    for route_book in source.route_books.values():
        route_book.wallet = source.wallet

    scalp_key = strategy_position_key("nvda", "scalp")
    swing_key = strategy_position_key("nvda", "swing")
    for key, mode, stop in (
        (scalp_key, "scalp", 95.0),
        (swing_key, "swing", 90.0),
    ):
        opened = source.wallet.open_position(
            "nvda",
            side="long",
            quantity=1,
            price=100.0,
            stop_price=stop,
            mode=mode,
            position_key=key,
            metadata={"routing_horizon": mode},
        )
        assert opened["ok"] is True
        route_book = source.route_books[key]
        route_book.entry_at = opened["opened_at"]
        route_book.entry_mode = mode
        route_book.stop = stop
        route_book.highest = (
            103.0 if mode == "scalp" else 110.0
        )
        route_book.lowest = (
            98.0 if mode == "scalp" else 92.0
        )

    state = {
        "wallet": source.wallet.payload(),
        "route_books": {
            key: {
                "stop": book.stop,
                "highest": book.highest,
                "lowest": book.lowest,
                "entry_at": book.entry_at,
                "entry_mode": book.entry_mode,
                "last_entry_signal_key": (
                    book.last_entry_signal_key
                ),
                "last_reason": book.last_reason,
                "fills": list(book.fills),
            }
            for key, book in source.route_books.items()
        },
    }

    restored = MultiDesk(execution_test_mode=False)
    restored._restore(state)

    assert restored.route_books[scalp_key].stop == 95.0
    assert restored.route_books[swing_key].stop == 90.0
    assert restored.route_books[scalp_key].entry_mode == "scalp"
    assert restored.route_books[swing_key].entry_mode == "swing"
    assert restored.route_books[scalp_key].highest == 103.0
    assert restored.route_books[swing_key].highest == 110.0

    closed = restored.wallet.close_position(
        "nvda",
        price=102.0,
        exit_reason="route_close",
        position_key=scalp_key,
    )
    assert closed["ok"] is True
    assert restored.wallet.position(
        "nvda",
        position_key=swing_key,
    ) is not None
