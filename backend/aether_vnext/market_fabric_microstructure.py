"""MF-07 non-executable microstructure intelligence.

All outputs in this module are explicitly derived Market Intelligence. They may
inform Strategy/Risk, but they can never overwrite Executable Tape prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import pstdev
from typing import Sequence


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: float
    size: float

    def __post_init__(self) -> None:
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not isfinite(self.size) or self.size < 0:
            raise ValueError("size must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class TradePrint:
    price: float
    size: float
    aggressor_side: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not isfinite(self.size) or self.size <= 0:
            raise ValueError("size must be finite and positive")
        if self.aggressor_side not in {None, "BUY", "SELL"}:
            raise ValueError("aggressor_side must be BUY, SELL, or None")


@dataclass(frozen=True, slots=True)
class MicrostructureSnapshot:
    spread_abs: float | None
    spread_bps: float | None
    top_depth_bid: float
    top_depth_ask: float
    depth_imbalance: float | None
    trade_imbalance: float | None
    quote_velocity_hz: float | None
    realized_volatility: float | None
    liquidity_score: float | None
    market_impact_proxy_bps: float | None

    @property
    def executable(self) -> bool:
        return False


def _mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
        return None
    return (bid + ask) / 2.0


def depth_imbalance(
    bids: Sequence[BookLevel],
    asks: Sequence[BookLevel],
    *,
    levels: int = 5,
) -> float | None:
    if levels < 1:
        raise ValueError("levels must be positive")
    bid_size = sum(level.size for level in bids[:levels])
    ask_size = sum(level.size for level in asks[:levels])
    total = bid_size + ask_size
    if total <= 0:
        return None
    return (bid_size - ask_size) / total


def trade_imbalance(trades: Sequence[TradePrint]) -> float | None:
    buy = sum(t.size for t in trades if t.aggressor_side == "BUY")
    sell = sum(t.size for t in trades if t.aggressor_side == "SELL")
    total = buy + sell
    if total <= 0:
        return None
    return (buy - sell) / total


def quote_velocity(
    quote_timestamps_ms: Sequence[int],
    *,
    window_ms: int,
) -> float | None:
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")
    if len(quote_timestamps_ms) < 2:
        return None
    ordered = tuple(int(v) for v in quote_timestamps_ms)
    if any(b < a for a, b in zip(ordered, ordered[1:])):
        raise ValueError("quote timestamps must be ordered")
    span = max(1, min(window_ms, ordered[-1] - ordered[0]))
    changes = len(ordered) - 1
    return changes / (span / 1000.0)


def realized_volatility(mid_prices: Sequence[float]) -> float | None:
    if len(mid_prices) < 3:
        return None
    returns = []
    for left, right in zip(mid_prices, mid_prices[1:]):
        if left <= 0 or right <= 0:
            raise ValueError("mid prices must be positive")
        returns.append((right - left) / left)
    return pstdev(returns) if len(returns) >= 2 else None


def build_microstructure_snapshot(
    *,
    bid: float | None,
    ask: float | None,
    bids: Sequence[BookLevel],
    asks: Sequence[BookLevel],
    trades: Sequence[TradePrint],
    quote_timestamps_ms: Sequence[int],
    mid_history: Sequence[float],
    velocity_window_ms: int,
    impact_notional: float,
) -> MicrostructureSnapshot:
    if impact_notional <= 0:
        raise ValueError("impact_notional must be positive")

    mid = _mid(bid, ask)
    spread_abs = None if mid is None else float(ask) - float(bid)
    spread_bps = (
        None
        if mid is None or spread_abs is None
        else spread_abs / mid * 10_000.0
    )
    top_bid_depth = sum(level.size for level in bids[:5])
    top_ask_depth = sum(level.size for level in asks[:5])
    imbalance = depth_imbalance(bids, asks)
    flow = trade_imbalance(trades)
    velocity = quote_velocity(quote_timestamps_ms, window_ms=velocity_window_ms)
    volatility = realized_volatility(mid_history)

    total_depth = top_bid_depth + top_ask_depth
    liquidity_score = None
    impact_proxy = None
    if mid is not None and total_depth > 0:
        # Bounded descriptive proxy only; not an execution price model.
        liquidity_score = total_depth / (1.0 + (spread_bps or 0.0))
        depth_notional = total_depth * mid
        impact_proxy = min(10_000.0, impact_notional / depth_notional * 10_000.0)

    return MicrostructureSnapshot(
        spread_abs=spread_abs,
        spread_bps=spread_bps,
        top_depth_bid=top_bid_depth,
        top_depth_ask=top_ask_depth,
        depth_imbalance=imbalance,
        trade_imbalance=flow,
        quote_velocity_hz=velocity,
        realized_volatility=volatility,
        liquidity_score=liquidity_score,
        market_impact_proxy_bps=impact_proxy,
    )
