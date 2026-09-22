"""Shared exit gates used by runtime and replay."""
from __future__ import annotations

TIME_STOP_BARS = 180
STOP_SLIP_BPS = 5.0


def time_stop_due(
    bars_held: int | None,
    gain_pct: float,
    cost_pct: float,
    limit: int = TIME_STOP_BARS,
) -> bool:
    if bars_held is None:
        return False
    return bars_held >= limit and gain_pct < cost_pct * 1.25


def stop_fill_price(
    stop: float,
    slip_bps: float = STOP_SLIP_BPS,
    *,
    side: str = "sell",
) -> float:
    """Conservative protective-stop fill for long sells or short covers."""
    slip = float(slip_bps) / 10_000.0
    if str(side).lower() == "buy":
        return float(stop) * (1 + slip)
    return float(stop) * (1 - slip)
