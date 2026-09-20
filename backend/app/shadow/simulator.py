"""Execution-suppressed shadow portfolio for strategy evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from app.execution import OrderRequest, PaperExecutionGateway
from app.portfolio import PaperPortfolio


@dataclass(frozen=True)
class ShadowExecution:
    side: str
    qty: float
    reference_price: float
    execution_price: float
    fee_usd: float
    spread_cost_usd: float
    slippage_cost_usd: float
    realized_net_pnl_usd: float | None
    applied: bool
    error: str | None

    def as_dict(self) -> dict:
        return asdict(self)


class ShadowSimulator:
    """Maintains a hypothetical portfolio without touching the real paper ledger."""

    def __init__(
        self,
        *,
        starting_usd: float,
        taker_fee_rate: float,
        spread_bps: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> None:
        self.portfolio = PaperPortfolio(starting_usd)
        self.execution = PaperExecutionGateway(
            taker_fee_rate=taker_fee_rate,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
        )
        self.executions: list[ShadowExecution] = []

    @property
    def in_position(self) -> bool:
        return self.portfolio.btc > 0

    @property
    def btc(self) -> float:
        return self.portfolio.btc

    @property
    def avg_entry(self) -> float:
        return self.portfolio.avg_entry

    async def execute(
        self,
        *,
        side: str,
        qty: float,
        mark: float,
    ) -> ShadowExecution:
        request = OrderRequest(
            client_order_id=f"aether-shadow-{uuid4().hex}",
            symbol="BTC/USD",
            side=side,
            qty=qty,
            reference_price=mark,
            actor="shadow",
        )
        fill = await self.execution.execute_market(request)
        applied, error, realized = self.portfolio.apply_fill(fill, mark)
        result = ShadowExecution(
            side=side,
            qty=fill.qty,
            reference_price=fill.reference_price,
            execution_price=fill.execution_price,
            fee_usd=fill.fee_usd,
            spread_cost_usd=fill.spread_cost_usd,
            slippage_cost_usd=fill.slippage_cost_usd,
            realized_net_pnl_usd=realized,
            applied=applied,
            error=error,
        )
        self.executions.append(result)
        return result

    def performance(self, mark: float | None) -> dict:
        snapshot = self.portfolio.snapshot(mark)
        return {
            "equity_usd": snapshot.equity,
            "btc": snapshot.btc,
            "avg_entry": snapshot.avg_entry,
            "open_pnl": snapshot.open_pnl,
            "realized_session": snapshot.realized_session,
            "gross_realized": snapshot.gross_realized,
            "total_fees": snapshot.total_fees,
            "total_spread_cost": snapshot.total_spread_cost,
            "total_slippage_cost": snapshot.total_slippage_cost,
            "max_drawdown_pct": snapshot.max_drawdown_pct,
            "closed_trade_count": snapshot.closed_trade_count,
            "winning_trades": snapshot.winning_trades,
            "losing_trades": snapshot.losing_trades,
            "win_rate_pct": snapshot.win_rate_pct,
            "avg_winner": snapshot.avg_winner,
            "avg_loser": snapshot.avg_loser,
            "execution_count": len(self.executions),
        }
