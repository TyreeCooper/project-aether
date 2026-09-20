"""Deterministic paper execution gateway.

Current behavior intentionally matches the previous engine: fill at mark and charge
a taker fee. Spread/slippage fields are explicit so later paper realism can be
added without changing the engine contract.
"""

from __future__ import annotations

from app.execution.base import ExecutionGateway, ExecutionResult, OrderRequest


class PaperExecutionGateway(ExecutionGateway):
    def __init__(self, taker_fee_rate: float) -> None:
        if taker_fee_rate < 0:
            raise ValueError("taker_fee_rate must be non-negative")
        self.taker_fee_rate = taker_fee_rate

    async def execute_market(self, request: OrderRequest) -> ExecutionResult:
        execution_price = request.reference_price
        fee = execution_price * request.qty * self.taker_fee_rate
        return ExecutionResult(
            client_order_id=request.client_order_id,
            side=request.side,
            qty=request.qty,
            reference_price=request.reference_price,
            execution_price=execution_price,
            fee_usd=fee,
        )
