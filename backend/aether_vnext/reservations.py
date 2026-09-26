"""Binding AETHER v4.2.1 broker-sleeve reservation math.

Portfolio uses these calculations at READY -> RESERVED.  The caller may supply
market truth and the READY ticket's stamped modeled round-trip cost percentage,
but may not invent reserve_cash or margin_need.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.costs import (
    DEFAULT_SLIP_BPS,
    default_short_borrow_usd,
    leg_fee_usd,
    notional_usd,
)
from aether_vnext.registry import ProductRegistryRow, ProductType


@dataclass(frozen=True, slots=True)
class ReservationRequirement:
    reserve_cash_usd: float
    margin_need_usd: float
    entry_reference_price: float
    computed_entry_price: float
    estimated_cost_buffer_usd: float
    entry_fee_usd: float
    borrow_buffer_usd: float


def reservation_requirement(
    row: ProductRegistryRow,
    *,
    side: str,
    qty: float,
    bid: float,
    ask: float,
    modeled_round_trip_cost_pct: float,
    slip_bps: float = DEFAULT_SLIP_BPS,
) -> ReservationRequirement:
    normalized_side = str(side).strip().lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    q = abs(float(qty))
    bid_px = float(bid)
    ask_px = float(ask)
    if q <= 0:
        raise ValueError("qty must be positive")
    if bid_px <= 0 or ask_px <= 0 or bid_px > ask_px:
        raise ValueError("valid non-crossed bid/ask required")
    if modeled_round_trip_cost_pct < 0:
        raise ValueError("modeled_round_trip_cost_pct cannot be negative")
    if slip_bps < 0:
        raise ValueError("slip_bps cannot be negative")

    reference = ask_px if normalized_side == "long" else bid_px
    computed_entry = (
        reference * (1.0 + slip_bps / 10_000.0)
        if normalized_side == "long"
        else reference * (1.0 - slip_bps / 10_000.0)
    )
    notional = notional_usd(row, qty=q, price=reference)
    modeled_rt_cost_usd = (
        notional * float(modeled_round_trip_cost_pct) / 100.0
    )

    if row.product_type is ProductType.SPOT_CRYPTO:
        if normalized_side != "long":
            raise ValueError("spot crypto short reserve is unsupported")
        entry_fee = leg_fee_usd(
            row,
            qty=q,
            price=computed_entry,
            side="buy",
        )
        reserve = q * computed_entry + entry_fee
        return ReservationRequirement(
            reserve_cash_usd=reserve,
            margin_need_usd=0.0,
            entry_reference_price=reference,
            computed_entry_price=computed_entry,
            estimated_cost_buffer_usd=entry_fee,
            entry_fee_usd=entry_fee,
            borrow_buffer_usd=0.0,
        )

    if row.product_type is ProductType.FX:
        if row.initial_margin is None:
            raise ValueError("FX initial margin is unbound")
        margin_need = notional * float(row.initial_margin)
        return ReservationRequirement(
            reserve_cash_usd=margin_need + modeled_rt_cost_usd,
            margin_need_usd=margin_need,
            entry_reference_price=reference,
            computed_entry_price=computed_entry,
            estimated_cost_buffer_usd=modeled_rt_cost_usd,
            entry_fee_usd=0.0,
            borrow_buffer_usd=0.0,
        )

    if row.product_type in {
        ProductType.MICRO_FUTURE,
        ProductType.TREASURY_FUTURE,
    }:
        if row.initial_margin is None:
            raise ValueError("futures initial margin is unbound")
        margin_need = q * float(row.initial_margin)
        return ReservationRequirement(
            reserve_cash_usd=margin_need + modeled_rt_cost_usd,
            margin_need_usd=margin_need,
            entry_reference_price=reference,
            computed_entry_price=computed_entry,
            estimated_cost_buffer_usd=modeled_rt_cost_usd,
            entry_fee_usd=0.0,
            borrow_buffer_usd=0.0,
        )

    if row.product_type is ProductType.EQUITY and normalized_side == "long":
        entry_fee = leg_fee_usd(
            row,
            qty=q,
            price=computed_entry,
            side="buy",
        )
        reserve = q * computed_entry + entry_fee
        return ReservationRequirement(
            reserve_cash_usd=reserve,
            margin_need_usd=0.0,
            entry_reference_price=reference,
            computed_entry_price=computed_entry,
            estimated_cost_buffer_usd=entry_fee,
            entry_fee_usd=entry_fee,
            borrow_buffer_usd=0.0,
        )

    if row.product_type is ProductType.EQUITY and normalized_side == "short":
        if row.initial_margin is None:
            raise ValueError("equity short margin is unbound")
        margin_need = notional * float(row.initial_margin)
        entry_fee = leg_fee_usd(
            row,
            qty=q,
            price=reference,
            side="sell",
        )
        borrow = default_short_borrow_usd(
            row,
            qty=q,
            price=reference,
            holding_days=1.0,
        )
        return ReservationRequirement(
            reserve_cash_usd=margin_need + entry_fee + borrow,
            margin_need_usd=margin_need,
            entry_reference_price=reference,
            computed_entry_price=computed_entry,
            estimated_cost_buffer_usd=entry_fee + borrow,
            entry_fee_usd=entry_fee,
            borrow_buffer_usd=borrow,
        )

    raise ValueError(
        f"unsupported reservation product/side: {row.product_type.value}/{normalized_side}"
    )
