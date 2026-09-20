"""Fail-closed pre-trade checks for paper and future live execution."""

from __future__ import annotations

from enum import Enum


class RiskDenyReason(str, Enum):
    FLATTEN_LOCK = "flatten_lock"
    LIVE_BLOCKED = "live_blocked"
    INVALID_QTY = "invalid_qty"
    MAX_POSITION = "max_position"
    MAX_DRAWDOWN = "max_drawdown"
    DAILY_LOSS_CAP = "daily_loss_cap"
    STALE_MARKET_DATA = "stale_market_data"
    SPREAD_TOO_WIDE = "spread_too_wide"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"


def deny_entry(
    *,
    flatten_lock: bool,
    paper_mode: bool,
    live_blocked: bool,
    qty: float,
    position_btc: float,
    max_position_btc: float,
    equity: float,
    peak_equity: float,
    max_drawdown_pct: float,
    daily_realized: float,
    daily_loss_cap: float,
    market_data_stale: bool = False,
    spread_bps: float | None = None,
    max_spread_bps: float | None = None,
    liquidity_ok: bool = True,
) -> str | None:
    if flatten_lock:
        return RiskDenyReason.FLATTEN_LOCK.value
    if live_blocked and not paper_mode:
        return RiskDenyReason.LIVE_BLOCKED.value
    if qty <= 0:
        return RiskDenyReason.INVALID_QTY.value
    if market_data_stale:
        return RiskDenyReason.STALE_MARKET_DATA.value
    if not liquidity_ok:
        return RiskDenyReason.INSUFFICIENT_LIQUIDITY.value
    if (
        spread_bps is not None
        and max_spread_bps is not None
        and spread_bps > max_spread_bps
    ):
        return RiskDenyReason.SPREAD_TOO_WIDE.value
    if position_btc + qty > max_position_btc + 1e-12:
        return RiskDenyReason.MAX_POSITION.value
    if peak_equity > 0:
        dd = (peak_equity - equity) / peak_equity * 100
        if dd >= max_drawdown_pct:
            return RiskDenyReason.MAX_DRAWDOWN.value
    if daily_realized <= -abs(daily_loss_cap):
        return RiskDenyReason.DAILY_LOSS_CAP.value
    return None
