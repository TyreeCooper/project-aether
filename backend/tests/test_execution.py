import asyncio

from app.execution import OrderRequest, PaperExecutionGateway


def test_paper_execution_preserves_reference_price_and_charges_fee():
    async def run():
        gateway = PaperExecutionGateway(taker_fee_rate=0.0026)
        request = OrderRequest.market(
            side="buy",
            qty=0.01,
            reference_price=50_000.0,
            actor="test",
        )
        return await gateway.execute_market(request)

    fill = asyncio.run(run())

    assert fill.execution_price == 50_000.0
    assert fill.reference_price == 50_000.0
    assert fill.qty == 0.01
    assert fill.fee_usd == 1.30
    assert fill.spread_cost_usd == 0.0
    assert fill.slippage_cost_usd == 0.0
    assert fill.client_order_id.startswith("aether-")
