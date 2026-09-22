"""Realistic, deterministic paper fill and transaction-cost model."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class FillCost:
    side: str
    qty: float
    reference_price: float
    fill_price: float
    notional: float
    fee: float
    slippage: float
    total_cost: float

def fill_cost(side: str, qty: float, *, bid: float | None, ask: float | None, mark: float | None, fee_rate: float, slippage_bps: float) -> FillCost | None:
    """Cross the quote, apply adverse slippage, then charge fee on executed notional."""
    side = str(side).lower()
    if side not in {"buy", "sell"} or qty <= 0:
        return None
    reference = ask if side == "buy" else bid
    if reference is None:
        reference = mark
    if reference is None or reference <= 0:
        return None
    slip = float(reference) * max(float(slippage_bps), 0.0) / 10_000.0
    price = float(reference) + slip if side == "buy" else float(reference) - slip
    notional = price * float(qty)
    fee = notional * max(float(fee_rate), 0.0)
    slippage = abs(price - float(reference)) * float(qty)
    return FillCost(side, float(qty), float(reference), price, notional, fee, slippage, fee + slippage)

def round_trip_cost(qty: float, *, bid: float, ask: float, fee_rate: float, slippage_bps: float) -> float:
    """Modeled spread + two fees + adverse slippage for buy then sell."""
    buy = fill_cost("buy", qty, bid=bid, ask=ask, mark=None, fee_rate=fee_rate, slippage_bps=slippage_bps)
    sell = fill_cost("sell", qty, bid=bid, ask=ask, mark=None, fee_rate=fee_rate, slippage_bps=slippage_bps)
    if buy is None or sell is None:
        return 0.0
    spread = max(float(ask) - float(bid), 0.0) * float(qty)
    return spread + buy.fee + sell.fee + buy.slippage + sell.slippage
