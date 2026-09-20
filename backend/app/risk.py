"""Pre-trade checks for paper and (later) live."""

from __future__ import annotations


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
) -> str | None:
    if flatten_lock:
        return "flatten_lock"
    if live_blocked and not paper_mode:
        return "live_blocked"
    if qty <= 0:
        return "invalid_qty"
    if position_btc + qty > max_position_btc + 1e-12:
        return "max_position"
    if peak_equity > 0:
        dd = (peak_equity - equity) / peak_equity * 100
        if dd >= max_drawdown_pct:
            return "max_drawdown"
    if daily_realized <= -abs(daily_loss_cap):
        return "daily_loss_cap"
    return None
