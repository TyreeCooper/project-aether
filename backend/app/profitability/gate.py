"""Economic gate between a strategy intent and the Risk Guard."""

from __future__ import annotations

from dataclasses import dataclass

from app.profitability.costs import CostEstimate, StaticCostModel


@dataclass(frozen=True)
class ProfitabilityDecision:
    allowed: bool
    enforced: bool
    reason: str
    expected_move_bps: float | None
    minimum_required_bps: float
    costs: CostEstimate


class ProfitabilityGate:
    def __init__(
        self,
        cost_model: StaticCostModel,
        *,
        minimum_edge_multiple: float = 1.25,
        enforce: bool = False,
    ) -> None:
        if minimum_edge_multiple <= 0:
            raise ValueError("minimum_edge_multiple must be positive")
        self.cost_model = cost_model
        self.minimum_edge_multiple = minimum_edge_multiple
        self.enforce = enforce

    def evaluate(
        self,
        *,
        qty: float,
        reference_price: float,
        expected_move_bps: float | None,
    ) -> ProfitabilityDecision:
        costs = self.cost_model.estimate(qty=qty, reference_price=reference_price)
        required = costs.total_cost_bps * self.minimum_edge_multiple

        if expected_move_bps is None:
            return ProfitabilityDecision(
                allowed=not self.enforce,
                enforced=self.enforce,
                reason="expected_edge_unavailable",
                expected_move_bps=None,
                minimum_required_bps=required,
                costs=costs,
            )

        allowed = expected_move_bps > required
        return ProfitabilityDecision(
            allowed=allowed,
            enforced=self.enforce,
            reason="edge_sufficient" if allowed else "edge_below_cost_threshold",
            expected_move_bps=expected_move_bps,
            minimum_required_bps=required,
            costs=costs,
        )
