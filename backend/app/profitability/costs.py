"""Pre-trade execution-cost estimates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostEstimate:
    fee_usd: float
    spread_cost_usd: float
    slippage_cost_usd: float
    total_cost_usd: float
    total_cost_bps: float


class StaticCostModel:
    """Simple explicit model used until live book/fill calibration is available."""

    def __init__(
        self,
        *,
        taker_fee_rate: float,
        spread_bps: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> None:
        if taker_fee_rate < 0 or spread_bps < 0 or slippage_bps < 0:
            raise ValueError("cost inputs must be non-negative")
        self.taker_fee_rate = taker_fee_rate
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps

    def estimate(self, *, qty: float, reference_price: float) -> CostEstimate:
        notional = qty * reference_price
        fee = notional * self.taker_fee_rate
        # Crossing the book pays approximately half the quoted spread from mid.
        spread_cost = notional * (self.spread_bps / 2.0) / 10_000.0
        slippage_cost = notional * self.slippage_bps / 10_000.0
        total = fee + spread_cost + slippage_cost
        total_bps = (total / notional * 10_000.0) if notional > 0 else 0.0
        return CostEstimate(
            fee_usd=fee,
            spread_cost_usd=spread_cost,
            slippage_cost_usd=slippage_cost,
            total_cost_usd=total,
            total_cost_bps=total_bps,
        )
