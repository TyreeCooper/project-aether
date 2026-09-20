from app.execution import ExecutionResult
from app.portfolio import PaperPortfolio


def _fill(*, side: str, qty: float, px: float, fee: float) -> ExecutionResult:
    return ExecutionResult(
        client_order_id="test-order",
        side=side,  # type: ignore[arg-type]
        qty=qty,
        reference_price=px,
        execution_price=px,
        fee_usd=fee,
        spread_cost_usd=0.0,
        slippage_cost_usd=0.0,
    )


def test_buy_fee_is_included_in_cost_basis():
    p = PaperPortfolio(starting_usd=10_000.0)

    ok, err, realized = p.apply_fill(_fill(side="buy", qty=0.1, px=1_000.0, fee=1.0), mark=1_000.0)

    assert ok is True
    assert err is None
    assert realized is None
    assert p.usd == 9_899.0
    assert p.btc == 0.1
    assert p.avg_entry == 1_000.0
    assert p.open_pnl(1_000.0) == -1.0
    assert p.total_fees == 1.0


def test_round_trip_realized_pnl_includes_entry_and_exit_fees():
    p = PaperPortfolio(starting_usd=10_000.0)
    p.apply_fill(_fill(side="buy", qty=0.1, px=1_000.0, fee=1.0), mark=1_000.0)
    p.apply_fill(_fill(side="sell", qty=0.1, px=1_100.0, fee=1.1), mark=1_100.0)

    # Gross move is $10; net subtracts $1 entry fee and $1.10 exit fee.
    assert round(p.realized_session, 2) == 7.90
    assert round(p.daily_realized, 2) == 7.90
    assert round(p.usd, 2) == 10_007.90
    assert p.btc == 0.0
    assert p.avg_entry == 0.0
    assert round(p.total_fees, 2) == 2.10


def test_partial_sell_preserves_remaining_cost_basis():
    p = PaperPortfolio(starting_usd=10_000.0)
    p.apply_fill(_fill(side="buy", qty=1.0, px=100.0, fee=1.0), mark=100.0)
    original_basis = p.avg_entry

    p.apply_fill(_fill(side="sell", qty=0.4, px=120.0, fee=0.5), mark=120.0)

    assert p.btc == 0.6
    assert p.avg_entry == original_basis


def test_trade_statistics_and_drawdown_are_tracked():
    p = PaperPortfolio(starting_usd=10_000.0)
    p.apply_fill(_fill(side="buy", qty=0.1, px=1_000.0, fee=0.0), mark=1_000.0)
    p.apply_fill(_fill(side="sell", qty=0.1, px=1_100.0, fee=0.0), mark=1_100.0)
    p.apply_fill(_fill(side="buy", qty=0.1, px=1_100.0, fee=0.0), mark=1_100.0)
    p.apply_fill(_fill(side="sell", qty=0.1, px=1_000.0, fee=0.0), mark=1_000.0)

    snap = p.snapshot(1_000.0)
    assert snap.closed_trade_count == 2
    assert snap.winning_trades == 1
    assert snap.losing_trades == 1
    assert snap.win_rate_pct == 50.0
    assert snap.avg_winner == 10.0
    assert snap.avg_loser == -10.0
    assert snap.max_drawdown_pct > 0
