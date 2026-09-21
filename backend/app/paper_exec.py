"""Harsh paper execution. Worse than mid-price; still not a live broker."""

from __future__ import annotations

SLIPPAGE_BPS = 5.0
MAX_SPREAD_BPS = 10.0
MAX_BASIS_USD = 80.0


def slipped_price(side: str, bid: float | None, ask: float | None, mark: float | None) -> float | None:
    raw = ask if side == "buy" else bid
    if raw is None:
        raw = mark
    if raw is None:
        return None
    slip = raw * SLIPPAGE_BPS / 10_000.0
    if side == "buy":
        return raw + slip
    return raw - slip


def deny_microstructure(
    *,
    side: str,
    bid: float | None,
    ask: float | None,
    mark: float | None,
    source: str | None,
    stale: bool,
    watch_last: float | None,
    protective: bool = False,
) -> str | None:
    if protective:
        return None
    if stale:
        return "stale_mark"
    if source == "coingecko":
        return "fallback_mark"
    if mark is None:
        return "no_mark"
    if bid is not None and ask is not None and bid > 0:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_bps = (ask - bid) / mid * 10_000.0
            if spread_bps > MAX_SPREAD_BPS:
                return "wide_spread"
    if watch_last is not None and mark is not None:
        if abs(float(watch_last) - float(mark)) > MAX_BASIS_USD:
            return "wide_basis"
    if slipped_price(side, bid, ask, mark) is None:
        return "no_mark"
    return None
