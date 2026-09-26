"""Binding AETHER vNext paper transaction-cost model.

Implements the later Part III closures:
- Kraken spot taker: 26 bps per leg + spread + 5 bps adverse slip.
- tastyfx: zero commission, but spread + 5 bps adverse slip remain.
- Ninja micros: $0.35 commission + $0.15 fees per side/contract + spread + 5 bps.
- IBKR equity: max($0.005/share, $1) per leg + SEC sell 0.0008% + spread
  + 5 bps; short borrow defaults to 50 bps/year when venue is silent.

All FX cost legs are converted to USD before the percentage. USDJPY quote-currency
costs divide by the current mark.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.registry import ProductRegistryRow


DEFAULT_SLIP_BPS = 5.0
KRAKEN_TAKER_BPS = 26.0
NINJA_COMMISSION_PER_SIDE = 0.35
NINJA_FEES_PER_SIDE = 0.15
IBKR_PER_SHARE = 0.005
IBKR_MIN_COMMISSION = 1.0
IBKR_SEC_SELL_RATE = 0.000008  # 0.0008%
IBKR_SILENT_SHORT_BORROW_ANNUAL = 0.005  # 50 bps/year
FX_STANDARD_LOT_BASE_UNITS = 100_000.0


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    entry_fee_usd: float
    exit_fee_usd: float
    slip_usd: float
    spread_usd: float
    carry_or_borrow_usd: float
    total_round_trip_cost_usd: float
    modeled_round_trip_cost_pct: float
    notional_usd: float
    cost_edge_multiple: float
    cost_hurdle_pct: float


def product_multiplier(row: ProductRegistryRow) -> float:
    if row.product_type.value == "fx":
        return FX_STANDARD_LOT_BASE_UNITS
    if row.point_value is not None:
        return float(row.point_value)
    return 1.0


def _quote_value_to_usd(
    row: ProductRegistryRow,
    *,
    quote_value: float,
    mark: float,
) -> float:
    if row.asset_id == "usdjpy":
        if mark <= 0:
            raise ValueError("USDJPY mark must be positive")
        return quote_value / mark
    return quote_value


def notional_usd(
    row: ProductRegistryRow,
    *,
    qty: float,
    price: float,
) -> float:
    q = abs(float(qty))
    px = float(price)
    if q <= 0 or px <= 0:
        raise ValueError("qty and price must be positive")
    if row.asset_id == "usdjpy":
        # Base currency is USD: 1.00 lot = 100,000 USD.
        return q * FX_STANDARD_LOT_BASE_UNITS
    return px * q * product_multiplier(row)


def leg_fee_usd(
    row: ProductRegistryRow,
    *,
    qty: float,
    price: float,
    side: str,
) -> float:
    notional = notional_usd(row, qty=qty, price=price)
    schedule = row.fee_schedule_id
    normalized_side = str(side).strip().lower()

    if schedule == "kraken_spot_taker_v1":
        return notional * (KRAKEN_TAKER_BPS / 10_000.0)

    if schedule == "tastyfx_allin_v1":
        return 0.0

    if schedule == "ninja_micros_v1":
        contracts = abs(float(qty))
        return contracts * (NINJA_COMMISSION_PER_SIDE + NINJA_FEES_PER_SIDE)

    if schedule == "ibkr_equity_v1":
        shares = abs(float(qty))
        commission = max(shares * IBKR_PER_SHARE, IBKR_MIN_COMMISSION)
        sec_sell = (
            notional * IBKR_SEC_SELL_RATE
            if normalized_side in {"sell", "short_exit_sell", "long_exit_sell"}
            else 0.0
        )
        return commission + sec_sell

    raise KeyError(f"unknown fee schedule: {schedule}")


def spread_cost_usd(
    row: ProductRegistryRow,
    *,
    qty: float,
    mark: float,
    spread_abs: float,
) -> float:
    if spread_abs < 0:
        raise ValueError("spread_abs must be non-negative")
    quote_cost = abs(float(spread_abs)) * abs(float(qty)) * product_multiplier(row)
    return _quote_value_to_usd(row, quote_value=quote_cost, mark=mark)


def slip_cost_usd(
    row: ProductRegistryRow,
    *,
    qty: float,
    price: float,
    slip_bps: float = DEFAULT_SLIP_BPS,
) -> float:
    if slip_bps < 0:
        raise ValueError("slip_bps must be non-negative")
    quote_cost = (
        float(price)
        * (float(slip_bps) / 10_000.0)
        * abs(float(qty))
        * product_multiplier(row)
    )
    return _quote_value_to_usd(row, quote_value=quote_cost, mark=price)


def default_short_borrow_usd(
    row: ProductRegistryRow,
    *,
    qty: float,
    price: float,
    holding_days: float,
    venue_borrow_rate_annual: float | None = None,
) -> float:
    if holding_days <= 0 or not row.borrow_required:
        return 0.0
    annual_rate = (
        float(venue_borrow_rate_annual)
        if venue_borrow_rate_annual is not None
        else IBKR_SILENT_SHORT_BORROW_ANNUAL
    )
    if annual_rate < 0:
        raise ValueError("borrow rate cannot be negative")
    return notional_usd(row, qty=qty, price=price) * annual_rate * (
        float(holding_days) / 365.0
    )


def modeled_round_trip_cost(
    row: ProductRegistryRow,
    *,
    qty: float,
    entry_price: float,
    exit_reference_price: float,
    spread_abs: float,
    entry_side: str,
    exit_side: str,
    slip_bps: float = DEFAULT_SLIP_BPS,
    cost_edge_multiple: float = 1.25,
    holding_days: float = 0.0,
    venue_borrow_rate_annual: float | None = None,
) -> CostBreakdown:
    if cost_edge_multiple < 1.0:
        raise ValueError("cost_edge_multiple cannot be below 1.00")
    entry_fee = leg_fee_usd(
        row,
        qty=qty,
        price=entry_price,
        side=entry_side,
    )
    exit_fee = leg_fee_usd(
        row,
        qty=qty,
        price=exit_reference_price,
        side=exit_side,
    )
    spread = spread_cost_usd(
        row,
        qty=qty,
        mark=entry_price,
        spread_abs=spread_abs,
    )
    entry_slip = slip_cost_usd(
        row,
        qty=qty,
        price=entry_price,
        slip_bps=slip_bps,
    )
    exit_slip = slip_cost_usd(
        row,
        qty=qty,
        price=exit_reference_price,
        slip_bps=slip_bps,
    )
    is_short_trade = str(entry_side).strip().lower() in {"sell", "short"}
    borrow = (
        default_short_borrow_usd(
            row,
            qty=qty,
            price=entry_price,
            holding_days=holding_days,
            venue_borrow_rate_annual=venue_borrow_rate_annual,
        )
        if is_short_trade
        else 0.0
    )
    total = entry_fee + exit_fee + entry_slip + exit_slip + spread + borrow
    denominator = notional_usd(row, qty=qty, price=entry_price)
    pct = (total / denominator) * 100.0
    return CostBreakdown(
        entry_fee_usd=entry_fee,
        exit_fee_usd=exit_fee,
        slip_usd=entry_slip + exit_slip,
        spread_usd=spread,
        carry_or_borrow_usd=borrow,
        total_round_trip_cost_usd=total,
        modeled_round_trip_cost_pct=pct,
        notional_usd=denominator,
        cost_edge_multiple=cost_edge_multiple,
        cost_hurdle_pct=pct * cost_edge_multiple,
    )


def ready_after_cost_hurdle(
    *,
    opportunity_pct: float,
    costs: CostBreakdown,
) -> bool:
    return float(opportunity_pct) > costs.cost_hurdle_pct
