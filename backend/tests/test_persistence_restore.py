import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.engine import PaperEngine


class FakeLedger:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.state = {
            "account": SimpleNamespace(
                usd=8750.0,
                btc=0.025,
                equity_usd=10_000.0,
                mark=50_000.0,
                entry_fees_open=3.25,
                realized_session=42.0,
                daily_realized=12.0,
                gross_realized=50.0,
                total_fees=8.0,
                total_spread_cost=1.0,
                total_slippage_cost=2.0,
                max_drawdown_pct=3.5,
                captured_at=now,
            ),
            "position": SimpleNamespace(
                avg_entry=49_000.0,
                peak_equity=10_100.0,
            ),
            "fills": [
                SimpleNamespace(
                    occurred_at=now,
                    client_order_id="aether-fill-1",
                    symbol="BTC/USD",
                    side="sell",
                    qty=0.01,
                    reference_price=50_000.0,
                    execution_price=50_000.0,
                    fee_usd=1.3,
                    spread_cost_usd=0.0,
                    slippage_cost_usd=0.0,
                    net_pnl_usd=8.7,
                    paper_mode=True,
                )
            ],
            "orders": [
                SimpleNamespace(
                    created_at=now,
                    client_order_id="aether-order-1",
                    symbol="BTC/USD",
                    side="buy",
                    qty=0.01,
                    reference_price=49_000.0,
                    actor="bot",
                    status="filled",
                    paper_mode=True,
                )
            ],
        }
        self.audit_events = []

    async def load_latest_state(self, symbol):
        assert symbol == "BTC/USD"
        return self.state

    async def record_audit(self, event):
        self.audit_events.append(event)
        return True

    async def record_order(self, order):
        return True

    async def record_fill(self, fill):
        return True

    async def save_portfolio(self, **kwargs):
        return True


def test_restore_persisted_state_is_fail_closed():
    ledger = FakeLedger()
    engine = PaperEngine(ledger=ledger)  # type: ignore[arg-type]

    asyncio.run(engine.restore_persisted_state())

    assert engine.state == "OFFLINE"
    assert engine.usd == 8750.0
    assert engine.btc == 0.025
    assert engine.avg_entry == 49_000.0
    assert engine.portfolio.entry_fees_open == 3.25
    assert len(engine.fills) == 1
    assert len(engine.orders) == 1
    assert engine.snapshot()["persistence_enabled"] is True


def test_no_ledger_keeps_persistence_disabled():
    engine = PaperEngine(ledger=None)
    # Constructor uses settings when ledger is None; test environment defaults false.
    assert engine.snapshot()["persistence_enabled"] is False
