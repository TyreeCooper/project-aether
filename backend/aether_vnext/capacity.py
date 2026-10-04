"""Intended-size capacity evidence for AETHER vNext profitability Review.

Part IV makes capacity part of edge. This module evaluates whether the intended
quantity remains economically positive after explicit intended-size friction and
whether source-required liquidity/borrow/carry inputs are complete.

It intentionally does not invent a universal spread percentile threshold, depth
threshold, slippage curve, or carry-materiality threshold. Those must arrive as
versioned route/product evidence or policy inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class CapacityEvidenceInput:
    intended_quantity: float
    expected_gross_edge_usd_per_trade: float
    base_round_trip_cost_usd_per_trade: float
    marginal_slippage_usd_per_trade: float | None
    gap_tail_cost_usd_per_trade: float | None
    spread_percentile: float | None
    spread_readiness: bool | None
    depth_data_available: bool
    depth_capacity_quantity: float | None
    conservative_product_cap_quantity: float | None
    locate_required: bool
    locate_available: bool | None
    borrow_cost_required: bool
    borrow_cost_usd_per_trade: float | None
    carry_cost_material: bool
    carry_cost_usd_per_trade: float | None

    def __post_init__(self) -> None:
        finite_required = (
            ("intended_quantity", self.intended_quantity),
            ("expected_gross_edge_usd_per_trade", self.expected_gross_edge_usd_per_trade),
            ("base_round_trip_cost_usd_per_trade", self.base_round_trip_cost_usd_per_trade),
        )
        for name, value in finite_required:
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if float(self.intended_quantity) <= 0.0:
            raise ValueError("intended_quantity must be positive")
        if float(self.base_round_trip_cost_usd_per_trade) < 0.0:
            raise ValueError("base_round_trip_cost_usd_per_trade cannot be negative")

        for name in (
            "marginal_slippage_usd_per_trade",
            "gap_tail_cost_usd_per_trade",
            "depth_capacity_quantity",
            "conservative_product_cap_quantity",
            "borrow_cost_usd_per_trade",
            "carry_cost_usd_per_trade",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")

        if self.spread_percentile is not None:
            percentile = float(self.spread_percentile)
            if not math.isfinite(percentile) or not 0.0 <= percentile <= 100.0:
                raise ValueError("spread_percentile must be in [0,100]")


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    intended_quantity: float
    applicable_capacity_quantity: float | None
    quantity_within_capacity: bool
    total_modeled_cost_usd_per_trade: float | None
    intended_size_net_expectancy_usd: float | None
    economically_positive_at_intended_size: bool
    trusted_keep_ready: bool
    unresolved_inputs: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    spread_percentile: float | None
    locate_status: str
    borrow_status: str
    carry_status: str
    depth_status: str

    def as_evidence_payload(self) -> dict[str, object]:
        return {
            "intended_quantity": self.intended_quantity,
            "applicable_capacity_quantity": self.applicable_capacity_quantity,
            "quantity_within_capacity": self.quantity_within_capacity,
            "total_modeled_cost_usd_per_trade": self.total_modeled_cost_usd_per_trade,
            "intended_size_net_expectancy_usd": self.intended_size_net_expectancy_usd,
            "economically_positive_at_intended_size": (
                self.economically_positive_at_intended_size
            ),
            "trusted_keep_ready": self.trusted_keep_ready,
            "unresolved_inputs": list(self.unresolved_inputs),
            "blocking_reasons": list(self.blocking_reasons),
            "spread_percentile": self.spread_percentile,
            "locate_status": self.locate_status,
            "borrow_status": self.borrow_status,
            "carry_status": self.carry_status,
            "depth_status": self.depth_status,
        }


def assess_capacity(value: CapacityEvidenceInput) -> CapacityAssessment:
    unresolved: list[str] = []
    blocked: list[str] = []

    if value.marginal_slippage_usd_per_trade is None:
        unresolved.append("marginal_slippage_curve_missing")
    if value.gap_tail_cost_usd_per_trade is None:
        unresolved.append("gap_tail_cost_missing")
    if value.spread_percentile is None:
        unresolved.append("spread_percentile_missing")
    if value.spread_readiness is None:
        unresolved.append("spread_readiness_policy_unbound")
    elif value.spread_readiness is False:
        blocked.append("spread_not_economically_ready")

    if value.depth_data_available:
        capacity_qty = value.depth_capacity_quantity
        depth_status = (
            "DEPTH_CAP_BOUND"
            if capacity_qty is not None
            else "DEPTH_CAP_MISSING"
        )
        if capacity_qty is None:
            unresolved.append("depth_capacity_quantity_missing")
    else:
        capacity_qty = value.conservative_product_cap_quantity
        depth_status = (
            "PRODUCT_CAP_BOUND"
            if capacity_qty is not None
            else "CONSERVATIVE_PRODUCT_CAP_MISSING"
        )
        if capacity_qty is None:
            unresolved.append("conservative_product_cap_quantity_missing")

    quantity_within_capacity = bool(
        capacity_qty is not None
        and float(value.intended_quantity) <= float(capacity_qty) + 1e-12
    )
    if capacity_qty is not None and not quantity_within_capacity:
        blocked.append("intended_quantity_exceeds_capacity")

    if value.locate_required:
        if value.locate_available is True:
            locate_status = "AVAILABLE"
        elif value.locate_available is False:
            locate_status = "UNAVAILABLE"
            blocked.append("required_locate_unavailable")
        else:
            locate_status = "UNKNOWN"
            unresolved.append("required_locate_unknown")
    else:
        locate_status = "NOT_REQUIRED"

    if value.borrow_cost_required:
        if value.borrow_cost_usd_per_trade is None:
            borrow_status = "UNKNOWN"
            unresolved.append("required_borrow_cost_unknown")
        else:
            borrow_status = "MODELED"
    else:
        borrow_status = "NOT_REQUIRED"

    if value.carry_cost_material:
        if value.carry_cost_usd_per_trade is None:
            carry_status = "UNKNOWN_MATERIAL"
            unresolved.append("material_carry_cost_unknown")
        else:
            carry_status = "MODELED"
    else:
        carry_status = "NOT_MATERIAL"

    economic_components = (
        value.marginal_slippage_usd_per_trade,
        value.gap_tail_cost_usd_per_trade,
        (
            value.borrow_cost_usd_per_trade
            if value.borrow_cost_required
            else 0.0
        ),
        (
            value.carry_cost_usd_per_trade
            if value.carry_cost_material
            else 0.0
        ),
    )
    economic_complete = all(component is not None for component in economic_components)

    total_cost: float | None = None
    net: float | None = None
    positive = False
    if economic_complete:
        total_cost = (
            float(value.base_round_trip_cost_usd_per_trade)
            + sum(float(component) for component in economic_components)
        )
        net = float(value.expected_gross_edge_usd_per_trade) - total_cost
        positive = net > 0.0
        if not positive:
            blocked.append("intended_size_net_expectancy_not_positive")

    ready = bool(
        not unresolved
        and not blocked
        and quantity_within_capacity
        and positive
    )

    return CapacityAssessment(
        intended_quantity=float(value.intended_quantity),
        applicable_capacity_quantity=(
            float(capacity_qty) if capacity_qty is not None else None
        ),
        quantity_within_capacity=quantity_within_capacity,
        total_modeled_cost_usd_per_trade=total_cost,
        intended_size_net_expectancy_usd=net,
        economically_positive_at_intended_size=positive,
        trusted_keep_ready=ready,
        unresolved_inputs=tuple(dict.fromkeys(unresolved)),
        blocking_reasons=tuple(dict.fromkeys(blocked)),
        spread_percentile=(
            float(value.spread_percentile)
            if value.spread_percentile is not None
            else None
        ),
        locate_status=locate_status,
        borrow_status=borrow_status,
        carry_status=carry_status,
        depth_status=depth_status,
    )
