"""AETHER vNext conservative sleeve-equity projection.

Resolves AETH-VN-007 by applying the explicit v3.1 anti-double-count law to the
later v4.2.1 sleeve fields.

Cash-purchase inventory (spot crypto and long equities) transforms reserved cash
into inventory. Its opening reserve therefore cannot also be counted as equity
while the inventory is marked at conservative bid.

Margin-style positions retain their reserved cash as capital and contribute
conservative unrealized P&L. margin_used itself is never subtracted again.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aether_vnext.execution import gross_pnl_usd
from aether_vnext.registry import ProductRegistryRow


@dataclass(frozen=True, slots=True)
class FirmEquityProjection:
    sleeves: tuple["SleeveEquityProjection", ...]
    consolidated_equity_usd: float


@dataclass(frozen=True, slots=True)
class SleeveEquityProjection:
    broker_account_id: str
    cash_available_usd: float
    cash_reserved_usd: float
    cash_inventory_backing_reserve_usd: float
    inventory_mtm_usd: float
    non_inventory_unrealized_pnl_usd: float
    fees_accrued_usd: float
    sleeve_equity_usd: float


def conservative_mark_price(*, side: str, bid: float, ask: float) -> float:
    normalized = str(side).strip().lower()
    bid_px = float(bid)
    ask_px = float(ask)
    if bid_px <= 0 or ask_px <= 0 or bid_px > ask_px:
        raise ValueError("valid non-crossed bid/ask required")
    if normalized == "long":
        return bid_px
    if normalized == "short":
        return ask_px
    raise ValueError("side must be long or short")


def inventory_market_value_usd(
    *,
    quantity: float,
    conservative_bid: float,
) -> float:
    qty = float(quantity)
    bid = float(conservative_bid)
    if qty < 0:
        raise ValueError("inventory quantity cannot be negative")
    if bid <= 0:
        raise ValueError("conservative bid must be positive")
    return qty * bid


def conservative_unrealized_pnl_usd(
    row: ProductRegistryRow,
    *,
    side: str,
    quantity: float,
    avg_entry_price: float,
    bid: float,
    ask: float,
) -> float:
    mark = conservative_mark_price(side=side, bid=bid, ask=ask)
    return gross_pnl_usd(
        row,
        position_side=side,
        qty=quantity,
        entry_price=avg_entry_price,
        exit_price=mark,
    )


def sleeve_equity_projection(
    *,
    broker_account_id: str,
    cash_available_usd: float,
    cash_reserved_usd: float,
    cash_inventory_backing_reserve_usd: float,
    inventory_mtm_usd: float,
    non_inventory_unrealized_pnl_usd: float,
    fees_accrued_usd: float,
) -> SleeveEquityProjection:
    cash_available = float(cash_available_usd)
    cash_reserved = float(cash_reserved_usd)
    inventory_backing = float(cash_inventory_backing_reserve_usd)
    inventory_mtm = float(inventory_mtm_usd)
    unrealized = float(non_inventory_unrealized_pnl_usd)
    fees = float(fees_accrued_usd)

    if cash_available < 0:
        raise ValueError("cash_available_usd cannot be negative")
    if cash_reserved < 0:
        raise ValueError("cash_reserved_usd cannot be negative")
    if inventory_backing < 0:
        raise ValueError("cash_inventory_backing_reserve_usd cannot be negative")
    if inventory_backing > cash_reserved + 1e-9:
        raise ValueError("inventory backing reserve cannot exceed cash_reserved_usd")
    if inventory_mtm < 0:
        raise ValueError("inventory_mtm_usd cannot be negative")
    if fees < 0:
        raise ValueError("fees_accrued_usd cannot be negative")

    equity = (
        cash_available
        + cash_reserved
        - inventory_backing
        + inventory_mtm
        + unrealized
        - fees
    )
    return SleeveEquityProjection(
        broker_account_id=str(broker_account_id),
        cash_available_usd=cash_available,
        cash_reserved_usd=cash_reserved,
        cash_inventory_backing_reserve_usd=inventory_backing,
        inventory_mtm_usd=inventory_mtm,
        non_inventory_unrealized_pnl_usd=unrealized,
        fees_accrued_usd=fees,
        sleeve_equity_usd=equity,
    )


def consolidated_equity_usd(
    projections: Iterable[SleeveEquityProjection],
) -> float:
    rows = tuple(projections)
    if not rows:
        raise ValueError("at least one sleeve projection is required")
    ids = [row.broker_account_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate broker_account_id in consolidated projection")
    return sum(row.sleeve_equity_usd for row in rows)



def firm_equity_projection(
    projections: Iterable[SleeveEquityProjection],
) -> FirmEquityProjection:
    rows = tuple(sorted(projections, key=lambda row: row.broker_account_id))
    return FirmEquityProjection(
        sleeves=rows,
        consolidated_equity_usd=consolidated_equity_usd(rows),
    )
