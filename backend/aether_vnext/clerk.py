"""Clerk exact paper-economics decision for AETHER vNext Phase 8.

Clerk receives a Risk-sized candidate. It may validate product-side/locate truth,
attach exact modeled round-trip economics, and decide whether the candidate clears
the strict opportunity-vs-cost hurdle. It cannot change Risk quantity, reserve
capital, admit Governor state, or mutate the shared book.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from aether_vnext.costs import (
    CostBreakdown,
    modeled_round_trip_cost,
    ready_after_cost_hurdle,
)
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.registry import ProductRegistryRow


@dataclass(frozen=True, slots=True)
class ClerkDecision:
    ready: bool
    reject_code: str | None
    opportunity_pct: float
    exit_reference_price: float
    costs: CostBreakdown | None
    locate_ok: bool

    @property
    def modeled_round_trip_cost_pct(self) -> float | None:
        return (
            None
            if self.costs is None
            else float(self.costs.modeled_round_trip_cost_pct)
        )

    @property
    def cost_hurdle_pct(self) -> float | None:
        return None if self.costs is None else float(self.costs.cost_hurdle_pct)

    @property
    def cost_headroom_score(self) -> float:
        if self.costs is None or self.opportunity_pct <= 0:
            return 0.0
        headroom = (
            100.0
            * (self.opportunity_pct - self.costs.cost_hurdle_pct)
            / self.opportunity_pct
        )
        return max(0.0, min(100.0, headroom))


def opportunity_and_exit_reference(
    *,
    side: str,
    entry_reference_price: float,
    first_target_price: float | None,
    atr: float | None,
) -> tuple[float, float]:
    """Return source-bound opportunity percent and economic exit reference.

    When the playbook has no first target, the source law substitutes 1.0x ATR
    from entry using ATR(14) of the trigger interval. The caller is responsible
    for supplying that source-correct ATR value.
    """
    normalized = str(side).strip().lower()
    if normalized not in {"long", "short"}:
        raise ValueError("side must be long or short")
    entry = float(entry_reference_price)
    if not math.isfinite(entry) or entry <= 0:
        raise ValueError("entry_reference_price must be finite and positive")

    if first_target_price is not None:
        target = float(first_target_price)
        if not math.isfinite(target) or target <= 0:
            raise ValueError("first_target_price must be finite and positive")
        if normalized == "long":
            favorable_move = target - entry
        else:
            favorable_move = entry - target
        if favorable_move <= 0:
            raise ValueError("first target is not favorable for ticket side")
        exit_reference = target
    else:
        if atr is None:
            raise ValueError("ATR is required when playbook has no first target")
        atr_value = float(atr)
        if not math.isfinite(atr_value) or atr_value <= 0:
            raise ValueError("ATR must be finite and positive")
        favorable_move = atr_value
        exit_reference = (
            entry + atr_value
            if normalized == "long"
            else entry - atr_value
        )
        if exit_reference <= 0:
            raise ValueError("ATR-derived exit reference must be positive")

    opportunity_pct = (favorable_move / entry) * 100.0
    return opportunity_pct, exit_reference


def evaluate_clerk_ready(
    row: ProductRegistryRow,
    *,
    side: str,
    qty: float,
    entry_reference_price: float,
    spread_abs: float,
    first_target_price: float | None,
    atr: float | None,
    locate_ok: bool = False,
    cost_edge_multiple: float = 1.25,
    holding_days: float = 0.0,
    venue_borrow_rate_annual: float | None = None,
) -> ClerkDecision:
    """Evaluate SIZE -> READY without changing Risk quantity."""
    normalized = str(side).strip().lower()
    quantity = float(qty)
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Risk-sized quantity must be finite and positive")
    if float(spread_abs) < 0:
        raise ValueError("spread_abs cannot be negative")

    if not row.product_side_supported(normalized, locate_ok=locate_ok):
        return ClerkDecision(
            ready=False,
            reject_code=ReasonCode.SIDE_NOT_SUPPORTED.value,
            opportunity_pct=0.0,
            exit_reference_price=float(entry_reference_price),
            costs=None,
            locate_ok=bool(locate_ok),
        )

    opportunity_pct, exit_reference = opportunity_and_exit_reference(
        side=normalized,
        entry_reference_price=entry_reference_price,
        first_target_price=first_target_price,
        atr=atr,
    )

    entry_side = "buy" if normalized == "long" else "sell"
    exit_side = "sell" if normalized == "long" else "buy"
    try:
        costs = modeled_round_trip_cost(
            row,
            qty=quantity,
            entry_price=float(entry_reference_price),
            exit_reference_price=exit_reference,
            spread_abs=float(spread_abs),
            entry_side=entry_side,
            exit_side=exit_side,
            cost_edge_multiple=float(cost_edge_multiple),
            holding_days=float(holding_days),
            venue_borrow_rate_annual=venue_borrow_rate_annual,
        )
    except (KeyError, ValueError, ZeroDivisionError):
        return ClerkDecision(
            ready=False,
            reject_code=ReasonCode.PRODUCT_COST_MODEL_ERROR.value,
            opportunity_pct=opportunity_pct,
            exit_reference_price=exit_reference,
            costs=None,
            locate_ok=bool(locate_ok),
        )

    ready = ready_after_cost_hurdle(
        opportunity_pct=opportunity_pct,
        costs=costs,
    )
    return ClerkDecision(
        ready=ready,
        reject_code=(
            None
            if ready
            else ReasonCode.COST_HURDLE_EXCEEDS_EXPECTED_MOVE.value
        ),
        opportunity_pct=opportunity_pct,
        exit_reference_price=exit_reference,
        costs=costs,
        locate_ok=bool(locate_ok),
    )
