"""Closed-bar clocks and loss budget. Shared by engine hook and journal."""
from __future__ import annotations

from typing import Any

from app.strategy import resample_bars


def five_minute_bucket(ts: int) -> int:
    return int(ts) // 300 * 300


def is_new_five_minute(bars_1m: list[dict[str, Any]], last_bucket: int | None) -> tuple[bool, int | None]:
    if not bars_1m:
        return False, last_bucket
    bucket = five_minute_bucket(int(bars_1m[-1].get("ts") or 0))
    if last_bucket is None or bucket != last_bucket:
        return True, bucket
    return False, last_bucket


def allow_after_losses(bars_1m: list[dict[str, Any]], consecutive_losses: int) -> bool:
    if consecutive_losses < 2:
        return True
    bars15 = resample_bars(bars_1m, 15)
    if len(bars15) < 4:
        return False
    prior = bars15[:-1][-8:]
    if not prior:
        return False
    return float(bars15[-1]["close"]) > max(float(b["high"]) for b in prior)


def close_in_upper_third(bar: dict[str, Any]) -> bool:
    high = float(bar.get("high") or 0)
    low = float(bar.get("low") or 0)
    close = float(bar.get("close") or 0)
    span = high - low
    if span <= 0:
        return False
    return (close - low) / span >= 0.70
