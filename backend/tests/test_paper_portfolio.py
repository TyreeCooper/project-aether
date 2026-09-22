from app.paper_portfolio import PaperPortfolio


def test_mes_long_and_short_use_contract_point_value():
    p = PaperPortfolio(20_000)
    q = p.size_for_risk(
        "mes",
        side="long",
        risk_usd=100,
        entry_price=5000.0,
        stop_price=4990.0,
    )
    assert q == 1.0
    opened = p.open_position("mes", side="long", quantity=1, price=5000.0)
    assert opened["ok"] is True
    assert p.gross_pnl("mes", 5002.0) == 10.0
    closed = p.close_position("mes", price=5002.0)
    assert closed["gross_pnl_usd"] == 10.0

    opened = p.open_position("mes", side="short", quantity=1, price=5000.0)
    assert opened["ok"] is True
    assert p.gross_pnl("mes", 4998.0) == 10.0


def test_mnq_mgc_mcl_and_10y_tick_values_are_correct():
    p = PaperPortfolio(50_000)
    cases = [
        ("mnq", 20000.0, 20000.25, 0.50),
        ("mgc", 2500.0, 2500.10, 1.00),
        ("mcl", 70.00, 70.01, 1.00),
        ("us10y", 4.250, 4.251, 1.00),
    ]
    for aid, entry, mark, expected in cases:
        opened = p.open_position(aid, side="long", quantity=1, price=entry)
        assert opened["ok"] is True
        assert round(p.gross_pnl(aid, mark), 6) == expected
        p.close_position(aid, price=entry)


def test_eurusd_and_usdjpy_pnl_convert_to_usd():
    p = PaperPortfolio(20_000)
    opened = p.open_position("eurusd", side="long", quantity=10_000, price=1.1000)
    assert opened["ok"] is True
    assert round(p.gross_pnl("eurusd", 1.1010), 6) == 10.0
    p.close_position("eurusd", price=1.1010)

    opened = p.open_position("usdjpy", side="short", quantity=10_000, price=150.00)
    assert opened["ok"] is True
    expected = (150.00 - 149.90) * 10_000 / 149.90
    assert round(p.gross_pnl("usdjpy", 149.90), 6) == round(expected, 6)


def test_equity_long_and_short_have_opposite_pnl_direction():
    p = PaperPortfolio(20_000)
    assert p.open_position("nvda", side="long", quantity=10, price=100)["ok"]
    assert p.gross_pnl("nvda", 102) == 20.0
    p.close_position("nvda", price=102)

    assert p.open_position("nvda", side="short", quantity=10, price=100)["ok"]
    assert p.gross_pnl("nvda", 98) == 20.0


def test_crypto_spot_rejects_short():
    p = PaperPortfolio(20_000)
    out = p.open_position("btc", side="short", quantity=0.01, price=100_000)
    assert out["ok"] is False
    assert out["error"] == "side_not_supported"


def test_duration_and_trade_id_survive_round_trip():
    p = PaperPortfolio(20_000)
    opened = p.open_position(
        "pltr",
        side="long",
        quantity=10,
        price=100,
        opened_at="2026-09-22T12:00:00+00:00",
        mode="intraday",
        signal_key="intraday:1",
    )
    closed = p.close_position(
        "pltr",
        price=101,
        closed_at="2026-09-22T12:43:46+00:00",
        exit_reason="rule_exit",
    )
    assert closed["trade_id"] == opened["trade_id"]
    assert closed["duration_seconds"] == 2626
    assert closed["mode"] == "intraday"
    assert closed["signal_key"] == "intraday:1"


def test_restore_preserves_open_position_identity():
    p = PaperPortfolio(20_000)
    opened = p.open_position(
        "eurusd",
        side="short",
        quantity=10_000,
        price=1.10,
        opened_at="2026-09-22T12:00:00+00:00",
    )
    payload = p.payload()
    restored = PaperPortfolio(1)
    restored.restore(payload)
    assert restored.position("eurusd")["trade_id"] == opened["trade_id"]
    assert restored.side("eurusd") == "short"
    assert restored.qty("eurusd") == 10_000
