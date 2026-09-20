import asyncio

from app.shadow import ShadowSimulator


def test_shadow_round_trip_models_costs_and_net_pnl():
    async def run():
        shadow = ShadowSimulator(
            starting_usd=10_000.0,
            taker_fee_rate=0.0026,
            spread_bps=10.0,
            slippage_bps=5.0,
        )
        buy = await shadow.execute(side="buy", qty=0.01, mark=50_000.0)
        sell = await shadow.execute(side="sell", qty=0.01, mark=51_000.0)
        return shadow, buy, sell

    shadow, buy, sell = asyncio.run(run())

    assert buy.applied is True
    assert sell.applied is True
    assert buy.execution_price > buy.reference_price
    assert sell.execution_price < sell.reference_price
    assert sell.realized_net_pnl_usd is not None

    performance = shadow.performance(51_000.0)
    assert performance["btc"] == 0.0
    assert performance["closed_trade_count"] == 1
    assert performance["total_fees"] > 0
    assert performance["total_spread_cost"] > 0
    assert performance["total_slippage_cost"] > 0


def test_shadow_simulator_never_uses_real_portfolio():
    async def run():
        shadow = ShadowSimulator(
            starting_usd=10_000.0,
            taker_fee_rate=0.0026,
        )
        await shadow.execute(side="buy", qty=0.01, mark=50_000.0)
        return shadow

    shadow = asyncio.run(run())
    assert shadow.btc == 0.01
    assert shadow.in_position is True
