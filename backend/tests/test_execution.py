import asyncio

from app.execution import OrderRequest, PaperExecutionGateway


def _run(gateway: PaperExecutionGateway, *, side: str = "buy"):
    async def run():
        request = OrderRequest.market(
            side=side,  # type: ignore[arg-type]
            qty=0.01,
            reference_price=50_000.0,
            actor="test",
        )
        return await gateway.execute_market(request)

    return asyncio.run(run())


def test_paper_execution_preserves_reference_price_and_charges_fee():
    fill = _run(PaperExecutionGateway(taker_fee_rate=0.0026))

    assert fill.execution_price == 50_000.0
    assert fill.reference_price == 50_000.0
    assert fill.qty == 0.01
    assert fill.fee_usd == 1.30
    assert fill.spread_cost_usd == 0.0
    assert fill.slippage_cost_usd == 0.0
    assert fill.client_order_id.startswith("aether-")


def test_buy_fill_moves_against_trader_for_spread_and_slippage():
    fill = _run(
        PaperExecutionGateway(
            taker_fee_rate=0.0,
            spread_bps=10.0,
            slippage_bps=5.0,
        ),
        side="buy",
    )

    assert round(fill.execution_price, 2) == 50_050.00
    assert round(fill.spread_cost_usd, 2) == 0.25
    assert round(fill.slippage_cost_usd, 2) == 0.25


def test_sell_fill_moves_against_trader_for_spread_and_slippage():
    fill = _run(
        PaperExecutionGateway(
            taker_fee_rate=0.0,
            spread_bps=10.0,
            slippage_bps=5.0,
        ),
        side="sell",
    )

    assert round(fill.execution_price, 2) == 49_950.00
