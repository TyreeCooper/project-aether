"""Shared exit gates used by runtime and replay."""
from __future__ import annotations

TIME_STOP_BARS = 180


def time_stop_due(
    bars_held: int | None,
    gain_pct: float,
    cost_pct: float,
    limit: int = TIME_STOP_BARS,
) -> bool:
    if bars_held is None:
        return False
    return bars_held >= limit and gain_pct < cost_pct * 1.25
