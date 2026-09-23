from app.desk import MultiDesk
from app.paper_portfolio import PaperPortfolio


def _test_desk() -> MultiDesk:
    desk = MultiDesk(execution_test_mode=True)
    desk.wallet = PaperPortfolio(10_000.0)
    for book in desk.books:
        book.wallet = desk.wallet
        book.mark = 100.0
        book.bid = 99.9
        book.ask = 100.1
        book.fills = []
        book.entry_at = None
        book.entry_mode = None
        book.last_entry_signal_key = None
    desk.armed = True
    return desk


def test_execution_test_mode_opens_all_twelve_books_at_minimum_step():
    desk = _test_desk()

    rows = desk._allocate()

    assert len(rows) == 12
    assert all(row.get("ok") is True for row in rows)
    assert len(desk.wallet.positions) == 12
    assert set(desk.wallet.positions) == {book.id for book in desk.books}

    for book in desk.books:
        pos = desk.wallet.position(book.id)
        assert pos is not None
        assert pos["side"] == "long"
        assert pos["mode"] == "execution_test"
        assert pos["execution_test_funded"] is True
        assert pos["metadata"]["execution_test"] is True
        assert pos["metadata"]["execution_test_load"] == "AETHER-LOAD-002"
        assert pos["margin_reserved_usd"] == 0.0


def test_execution_test_mode_does_not_change_normal_constructor_default():
    desk = MultiDesk()
    assert desk.execution_test_mode is False
    assert desk.engine_status()["execution_test_mode"] is False


def test_execution_test_funding_does_not_reserve_normal_margin():
    portfolio = PaperPortfolio(10_000.0)
    before = portfolio.usd
    opened = portfolio.open_position(
        "us10y",
        side="long",
        quantity=1,
        price=100.0,
        stop_price=90.0,
        mode="execution_test",
        execution_test=True,
        metadata={"execution_test": True},
    )
    assert opened["ok"] is True
    assert opened["normal_required_margin_usd"] > 0
    assert opened["margin_reserved_usd"] == 0.0
    assert portfolio.usd <= before
    assert portfolio.usd > before - opened["normal_required_margin_usd"]


def test_test_mode_status_is_explicit_and_live_boundary_remains_blocked():
    desk = MultiDesk(execution_test_mode=True)
    status = desk.engine_status()
    settings = desk.settings_snapshot()
    assert status["execution_test_mode"] is True
    assert status["live_blocked"] is True
    assert settings["execution_test_mode"] is True
    assert settings["execution_test_load"] == "AETHER-LOAD-002"


def test_execution_test_position_keeps_unmistakable_identity_through_close():
    portfolio = PaperPortfolio(10_000.0)
    opened = portfolio.open_position(
        "btc",
        side="long",
        quantity=0.0001,
        price=100_000.0,
        stop_price=90_000.0,
        mode="execution_test",
        execution_test=True,
        metadata={
            "execution_test": True,
            "execution_test_load": "AETHER-LOAD-002",
        },
    )
    assert opened["ok"] is True

    closed = portfolio.close_position(
        "btc",
        price=101_000.0,
        exit_reason="test_close",
    )
    assert closed["ok"] is True
    assert closed["mode"] == "execution_test"
    assert closed["execution_test_funded"] is True
    assert closed["metadata"]["execution_test"] is True
    assert closed["metadata"]["execution_test_load"] == "AETHER-LOAD-002"

    durable = portfolio.closed_trades[-1]
    assert durable["trade_id"] == opened["trade_id"]
    assert durable["mode"] == "execution_test"
    assert durable["execution_test_funded"] is True
    assert durable["metadata"]["execution_test_load"] == "AETHER-LOAD-002"


def test_live_order_rail_remains_hard_blocked_in_execution_test(monkeypatch):
    import asyncio
    from app import live

    monkeypatch.setenv("AETHER_LIVE", "1")
    monkeypatch.setenv("KRAKEN_API_KEY", "test-key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "test-secret")

    result = asyncio.run(
        live.place_order(
            pair="XBTUSD",
            side="buy",
            volume=0.0001,
            execution_test=True,
        )
    )

    assert result["ok"] is False
    assert result["error"] == "live_orders_blocked"
    assert result["live_flag"] is True
    assert result["live_armed"] is False
    assert result["orders_enabled"] is False


def test_normal_mode_never_forces_entry_when_strategy_has_no_signal(monkeypatch):
    desk = _test_desk()
    desk.execution_test_mode = False

    for book in desk.books:
        monkeypatch.setattr(
            book,
            "snapshot_strategy",
            lambda **_kwargs: {
                "signal": None,
                "executable_signal": None,
                "reason": "no_setup",
                "execution_status": "waiting",
                "quality_score": 0,
            },
        )

    assert desk._allocate() == []
    assert desk.wallet.positions == {}


def test_execution_override_preserves_baseline_strategy_diagnostics(monkeypatch):
    desk = _test_desk()

    for book in desk.books:
        monkeypatch.setattr(
            book,
            "snapshot_strategy",
            lambda **_kwargs: {
                "signal": None,
                "executable_signal": None,
                "reason": "normal_gate_blocked",
                "execution_status": "waiting_for_setup",
                "quality_score": 37,
            },
        )

    rows = desk._allocate()
    assert len(rows) == 12
    assert all(row["ok"] is True for row in rows)

    for book in desk.books:
        pos = desk.wallet.position(book.id)
        assert pos is not None
        metadata = pos["metadata"]
        assert metadata["execution_test"] is True
        assert metadata["execution_test_load"] == "AETHER-LOAD-002"
        assert metadata["would_have_blocked_by"] == "normal_gate_blocked"
        assert metadata["normal_execution_status"] == "waiting_for_setup"
        assert metadata["normal_signal"] is None
        assert metadata["normal_quality_score"] == 37


def test_live_trade_view_exposes_execution_test_identity_and_baseline(monkeypatch):
    desk = _test_desk()
    for book in desk.books:
        monkeypatch.setattr(
            book,
            "snapshot_strategy",
            lambda **_kwargs: {
                "signal": None,
                "executable_signal": None,
                "reason": "normal_gate_blocked",
                "execution_status": "waiting_for_setup",
                "quality_score": 41,
            },
        )

    desk._allocate()
    live = desk.live_trades()

    assert live["open_count"] == 12
    for row in live["items"]:
        assert row["execution_test"] is True
        assert row["execution_test_load"] == "AETHER-LOAD-002"
        assert row["would_have_blocked_by"] == "normal_gate_blocked"
        assert row["normal_execution_status"] == "waiting_for_setup"
        assert row["normal_signal"] is None
        assert row["normal_quality_score"] == 41


def test_blotter_keeps_execution_test_identity_and_duration_after_close():
    desk = _test_desk()
    book = desk.books[0]
    rows = desk._allocate()
    opened = next(row for row in rows if row["pair"] == book.pair)
    trade_id = opened["trade_id"]
    position = desk.wallet.position(book.id)
    assert position is not None

    closed = desk.wallet.close_position(
        book.id,
        price=float(position["entry_price"]) * 1.01,
        closed_at="2026-09-23T08:10:30+00:00",
        exit_reason="execution_test_close",
    )
    assert closed["ok"] is True

    # Fix the synthetic test timestamps so duration is deterministic.
    durable = desk.wallet.closed_trades[-1]
    durable["opened_at"] = "2026-09-23T08:00:00+00:00"
    durable["closed_at"] = "2026-09-23T08:10:30+00:00"
    durable["duration_seconds"] = 630

    blotter = desk.blotter()
    row = next(item for item in blotter if item["trade_id"] == trade_id)

    assert row["mode"] == "execution_test"
    assert row["execution_test_funded"] is True
    assert row["metadata"]["execution_test"] is True
    assert row["metadata"]["execution_test_load"] == "AETHER-LOAD-002"
    assert row["duration_seconds"] == 630


def test_normal_blotter_trade_is_not_mislabeled_as_execution_test():
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(10_000.0)
    for book in desk.books:
        book.wallet = desk.wallet

    opened = desk.wallet.open_position(
        "btc",
        side="long",
        quantity=0.0001,
        price=100_000.0,
        stop_price=98_000.0,
        mode="intraday",
        metadata={"entry_reason": "normal_strategy"},
    )
    assert opened["ok"] is True
    closed = desk.wallet.close_position(
        "btc",
        price=101_000.0,
        exit_reason="strategy_exit",
    )
    assert closed["ok"] is True

    row = next(
        item for item in desk.blotter()
        if item["trade_id"] == opened["trade_id"]
    )
    assert row["mode"] == "intraday"
    assert row["execution_test_funded"] is False
    assert row["metadata"].get("execution_test") is not True
