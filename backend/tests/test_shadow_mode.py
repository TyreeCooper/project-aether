import asyncio

from app.engine import PaperEngine


def test_shadow_decision_is_recorded_without_execution():
    async def run():
        engine = PaperEngine()
        engine.mark = 100_000.0
        before_orders = len(engine.orders)
        before_fills = len(engine.fills)

        await engine._record_shadow_decision(
            signal="buy",
            qty=0.01,
            would_execute=True,
            reason="test_signal",
        )
        return engine, before_orders, before_fills

    engine, before_orders, before_fills = asyncio.run(run())

    assert len(engine.shadow_decisions) == 1
    assert len(engine.orders) == before_orders
    assert len(engine.fills) == before_fills

    decision = engine.shadow_decisions[0]
    assert decision["signal"] == "buy"
    assert decision["would_execute"] is True
    assert decision["reason"] == "test_signal"
