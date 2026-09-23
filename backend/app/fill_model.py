"""Realistic, deterministic paper fill and transaction-cost model."""
from __future__ import annotations
from dataclasses import dataclass

SLIPPAGE_BPS = 5.0


def market_reference_price(
    *,
    bid: float | None,
    ask: float | None,
    mark: float | None,
) -> float | None:
    if (
        bid is not None
        and ask is not None
        and float(bid) > 0
        and float(ask) >= float(bid)
    ):
        return (float(bid) + float(ask)) / 2.0
    if mark is not None and float(mark) > 0:
        return float(mark)
    if bid is not None and float(bid) > 0:
        return float(bid)
    if ask is not None and float(ask) > 0:
        return float(ask)
    return None


def quote_reference_price(
    side: str,
    *,
    bid: float | None,
    ask: float | None,
    mark: float | None,
) -> float | None:
    execution_side = str(side).lower()
    if execution_side == "buy":
        if ask is not None and float(ask) > 0:
            return float(ask)
    elif execution_side == "sell":
        if bid is not None and float(bid) > 0:
            return float(bid)
    else:
        return None
    return market_reference_price(
        bid=bid,
        ask=ask,
        mark=mark,
    )


def modeled_fill_price(
    side: str,
    *,
    bid: float | None,
    ask: float | None,
    mark: float | None,
    slippage_bps: float = SLIPPAGE_BPS,
) -> float | None:
    execution_side = str(side).lower()
    reference = quote_reference_price(
        execution_side,
        bid=bid,
        ask=ask,
        mark=mark,
    )
    if reference is None:
        return None
    slip = float(reference) * max(
        float(slippage_bps),
        0.0,
    ) / 10_000.0
    return (
        float(reference) + slip
        if execution_side == "buy"
        else float(reference) - slip
    )


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
    reference = quote_reference_price(
        side,
        bid=bid,
        ask=ask,
        mark=mark,
    )
    if reference is None:
        return None
    price = modeled_fill_price(
        side,
        bid=bid,
        ask=ask,
        mark=mark,
        slippage_bps=slippage_bps,
    )
    if price is None:
        return None
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
