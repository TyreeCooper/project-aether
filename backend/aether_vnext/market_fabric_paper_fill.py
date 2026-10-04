"""MF-09 depth- and latency-aware PAPER fill model.

PAPER fills are derived only from the authorized executable route. The model records
its fidelity tier, modeled latency, fees, and liquidity-stress assumptions. It never
uses witness-derived prices as executable prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Sequence


class PaperFidelity(StrEnum):
    L2_WALK = "L2_WALK"
    L1_CAPPED = "L1_CAPPED"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: float
    size: float

    def __post_init__(self) -> None:
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not isfinite(self.size) or self.size < 0:
            raise ValueError("size must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PaperFillPolicy:
    policy_version: str
    modeled_latency_ms: int
    fee_bps: float
    max_participation: float
    l1_quantity_cap: float | None
    reject_on_insufficient_depth: bool

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.modeled_latency_ms < 0:
            raise ValueError("modeled_latency_ms cannot be negative")
        if self.fee_bps < 0:
            raise ValueError("fee_bps cannot be negative")
        if not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0,1]")
        if self.l1_quantity_cap is not None and self.l1_quantity_cap <= 0:
            raise ValueError("l1_quantity_cap must be positive when set")


@dataclass(frozen=True, slots=True)
class PaperFillResult:
    accepted: bool
    side: str
    requested_quantity: float
    filled_quantity: float
    average_price: float | None
    gross_notional: float
    fee_usd: float
    fidelity: PaperFidelity
    modeled_latency_ms: int
    liquidity_stress_applied: bool
    rejection_reason: str | None

    @property
    def live_execution_authorized(self) -> bool:
        return False


def _validate_side(side: str) -> str:
    value = str(side).strip().upper()
    if value not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return value


def simulate_paper_fill(
    *,
    side: str,
    quantity: float,
    bid_levels: Sequence[DepthLevel],
    ask_levels: Sequence[DepthLevel],
    policy: PaperFillPolicy,
    l2_available: bool,
) -> PaperFillResult:
    normalized_side = _validate_side(side)
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity must be finite and positive")

    levels = tuple(ask_levels if normalized_side == "BUY" else bid_levels)
    if not levels:
        return PaperFillResult(
            accepted=False,
            side=normalized_side,
            requested_quantity=quantity,
            filled_quantity=0.0,
            average_price=None,
            gross_notional=0.0,
            fee_usd=0.0,
            fidelity=PaperFidelity.NONE,
            modeled_latency_ms=policy.modeled_latency_ms,
            liquidity_stress_applied=False,
            rejection_reason="EXECUTABLE_DEPTH_NOT_OBSERVED",
        )

    if l2_available:
        fidelity = PaperFidelity.L2_WALK
        available = sum(level.size * policy.max_participation for level in levels)
        if available + 1e-12 < quantity and policy.reject_on_insufficient_depth:
            return PaperFillResult(
                accepted=False,
                side=normalized_side,
                requested_quantity=quantity,
                filled_quantity=0.0,
                average_price=None,
                gross_notional=0.0,
                fee_usd=0.0,
                fidelity=fidelity,
                modeled_latency_ms=policy.modeled_latency_ms,
                liquidity_stress_applied=True,
                rejection_reason="INSUFFICIENT_DISPLAYED_DEPTH",
            )
        remaining = quantity
        fills: list[tuple[float, float]] = []
        for level in levels:
            capacity = level.size * policy.max_participation
            if capacity <= 0:
                continue
            take = min(remaining, capacity)
            if take > 0:
                fills.append((level.price, take))
                remaining -= take
            if remaining <= 1e-12:
                break
        filled = quantity - max(remaining, 0.0)
    else:
        fidelity = PaperFidelity.L1_CAPPED
        top = levels[0]
        cap = top.size * policy.max_participation
        if policy.l1_quantity_cap is not None:
            cap = min(cap, policy.l1_quantity_cap)
        if quantity > cap + 1e-12 and policy.reject_on_insufficient_depth:
            return PaperFillResult(
                accepted=False,
                side=normalized_side,
                requested_quantity=quantity,
                filled_quantity=0.0,
                average_price=None,
                gross_notional=0.0,
                fee_usd=0.0,
                fidelity=fidelity,
                modeled_latency_ms=policy.modeled_latency_ms,
                liquidity_stress_applied=True,
                rejection_reason="L1_QUANTITY_CAP_EXCEEDED",
            )
        filled = min(quantity, cap)
        fills = [(top.price, filled)] if filled > 0 else []

    if filled <= 0 or not fills:
        return PaperFillResult(
            accepted=False,
            side=normalized_side,
            requested_quantity=quantity,
            filled_quantity=0.0,
            average_price=None,
            gross_notional=0.0,
            fee_usd=0.0,
            fidelity=fidelity,
            modeled_latency_ms=policy.modeled_latency_ms,
            liquidity_stress_applied=True,
            rejection_reason="NO_FILLABLE_EXECUTABLE_LIQUIDITY",
        )

    gross = sum(price * qty for price, qty in fills)
    average = gross / filled
    fee = gross * policy.fee_bps / 10_000.0
    partial = filled + 1e-12 < quantity
    return PaperFillResult(
        accepted=not partial or not policy.reject_on_insufficient_depth,
        side=normalized_side,
        requested_quantity=quantity,
        filled_quantity=filled,
        average_price=average,
        gross_notional=gross,
        fee_usd=fee,
        fidelity=fidelity,
        modeled_latency_ms=policy.modeled_latency_ms,
        liquidity_stress_applied=(len(fills) > 1 or partial),
        rejection_reason="PARTIAL_FILL" if partial else None,
    )
