"""Closed-bar clocks and horizon scheduling. Shared by paper strategy components."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.horizons import HORIZON_REGISTRY, TradingHorizon
from app.strategy import resample_bars

HORIZON_BAR_SECONDS: dict[TradingHorizon, int] = {
    TradingHorizon.HFT: 1,
    TradingHorizon.SCALP: 60,
    TradingHorizon.INTRADAY: 5 * 60,
    TradingHorizon.SWING: 60 * 60,
    TradingHorizon.POSITION: 24 * 60 * 60,
}

def horizon_bucket(ts: int, horizon: TradingHorizon | str) -> int:
    key = horizon if isinstance(horizon, TradingHorizon) else TradingHorizon(str(horizon).lower())
    seconds = HORIZON_BAR_SECONDS[key]
    return int(ts) // seconds * seconds

def five_minute_bucket(ts: int) -> int:
    return horizon_bucket(ts, TradingHorizon.INTRADAY)

@dataclass
class HorizonController:
    """At-most-once scheduler driven by completed one-minute source bars."""
    last_bucket: dict[TradingHorizon, int] = field(default_factory=dict)

    def due(self, closed_ts: int, *, include_gated: bool = False) -> tuple[TradingHorizon, ...]:
        ts = int(closed_ts)
        due: list[TradingHorizon] = []
        for horizon, spec in HORIZON_REGISTRY.items():
            if not include_gated and not spec.execution_enabled:
                continue
            seconds = HORIZON_BAR_SECONDS[horizon]
            bucket = horizon_bucket(ts, horizon)
            if ts + 60 < bucket + seconds:
                continue
            if self.last_bucket.get(horizon) == bucket:
                continue
            self.last_bucket[horizon] = bucket
            due.append(horizon)
        return tuple(due)

def due_horizons(closed_ts: int, last_buckets: Mapping[TradingHorizon | str, int] | None = None, *, include_gated: bool = False) -> tuple[tuple[TradingHorizon, ...], dict[TradingHorizon, int]]:
    controller = HorizonController()
    if last_buckets:
        for horizon, bucket in last_buckets.items():
            key = horizon if isinstance(horizon, TradingHorizon) else TradingHorizon(str(horizon).lower())
            controller.last_bucket[key] = int(bucket)
    due = controller.due(closed_ts, include_gated=include_gated)
    return due, dict(controller.last_bucket)

def is_new_five_minute(bars_1m: list[dict[str, Any]], last_bucket: int | None) -> tuple[bool, int | None]:
    if not bars_1m:
        return False, last_bucket
    bucket = five_minute_bucket(int(bars_1m[-1].get("ts") or 0))
    if last_bucket is None:
        return False, bucket
    if bucket != last_bucket:
        return True, bucket
    return False, last_bucket

def allow_after_losses(bars_1m: list[dict[str, Any]], consecutive_losses: int) -> bool:
    if consecutive_losses < 2:
        return True
    bars15 = resample_bars(bars_1m, 15, require_complete=True)
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
