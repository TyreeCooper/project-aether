"""Execution contracts shared by paper and future venue adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class OrderRequest:
    side: Side
    qty: float
    reference_price: float
    actor: str
    client_order_id: str

    @classmethod
    def market(cls, *, side: Side, qty: float, reference_price: float, actor: str) -> "OrderRequest":
        return cls(
            side=side,
            qty=qty,
            reference_price=reference_price,
            actor=actor,
            client_order_id=f"aether-{uuid4().hex}",
        )


@dataclass(frozen=True)
class ExecutionResult:
    client_order_id: str
    side: Side
    qty: float
    reference_price: float
    execution_price: float
    fee_usd: float
    spread_cost_usd: float = 0.0
    slippage_cost_usd: float = 0.0


class DuplicateOrderError(RuntimeError):
    pass


class ExecutionGateway(ABC):
    @abstractmethod
    async def execute_market(self, request: OrderRequest) -> ExecutionResult:
        """Execute an order request and return normalized execution details."""
