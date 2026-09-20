"""Deterministic paper execution gateway with explicit execution costs."""

from __future__ import annotations

from app.execution.base import DuplicateOrderError, ExecutionGateway, ExecutionResult, OrderRequest


class PaperExecutionGateway(ExecutionGateway):
    def __init__(
        self,
        taker_fee_rate: float,
        *,
        spread_bps: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> None:
        if taker_fee_rate < 0 or spread_bps < 0 or slippage_bps < 0:
            raise ValueError("execution cost inputs must be non-negative")
        self.taker_fee_rate = taker_fee_rate
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps
        self._seen_client_order_ids: set[str] = set()

    async def execute_market(self, request: OrderRequest) -> ExecutionResult:
        if request.client_order_id in self._seen_client_order_ids:
            raise DuplicateOrderError(
                f"duplicate client_order_id: {request.client_order_id}"
            )
        self._seen_client_order_ids.add(request.client_order_id)

        half_spread_fraction = (self.spread_bps / 2.0) / 10_000.0
        slippage_fraction = self.slippage_bps / 10_000.0
        direction = 1.0 if request.side == "buy" else -1.0

        execution_price = request.reference_price * (
            1.0 + direction * (half_spread_fraction + slippage_fraction)
        )
        spread_cost = (
            request.reference_price
            * request.qty
            * half_spread_fraction
        )
        slippage_cost = (
            request.reference_price
            * request.qty
            * slippage_fraction
        )
        fee = execution_price * request.qty * self.taker_fee_rate

        return ExecutionResult(
            client_order_id=request.client_order_id,
            side=request.side,
            qty=request.qty,
            reference_price=request.reference_price,
            execution_price=execution_price,
            fee_usd=fee,
            spread_cost_usd=spread_cost,
            slippage_cost_usd=slippage_cost,
        )
