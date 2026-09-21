"""Trend-aware SMA strategy primitives shared by runtime and replay."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

Bar = dict[str, Any]


def sma(values: list[float], length: int) -> float | None:
    if length <= 0 or len(values) < length:
        return None
    window = values[-length:]
    return sum(window) / length


def crossover_signal(
    closes: list[float],
    short_len: int,
    long_len: int,
    in_position: bool,
) -> str | None:
    if short_len >= long_len or len(closes) < long_len + 1:
        return None
    prev_short = sma(closes[:-1], short_len)
    prev_long = sma(closes[:-1], long_len)
    cur_short = sma(closes, short_len)
    cur_long = sma(closes, long_len)
    if None in (prev_short, prev_long, cur_short, cur_long):
        return None
    if not in_position and prev_short <= prev_long and cur_short > cur_long:
        return "buy"
    if in_position and prev_short >= prev_long and cur_short < cur_long:
        return "sell"
    return None


def _bar_ts(bar: Bar) -> int:
    raw = bar.get("ts", 0)
    if isinstance(raw, datetime):
        return int(raw.timestamp())
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def normalize_bar(bar: Bar) -> Bar:
    close = float(bar.get("close", bar.get("c", 0)) or 0)
    open_ = float(bar.get("open", bar.get("o", close)) or close)
    high = float(bar.get("high", bar.get("h", close)) or close)
    low = float(bar.get("low", bar.get("l", close)) or close)
    return {
        "ts": _bar_ts(bar),
        "open": open_,
        "high": max(high, open_, close),
        "low": min(low, open_, close),
        "close": close,
        "volume": float(bar.get("volume", bar.get("v", 0)) or 0),
    }


def resample_bars(bars: list[Bar], minutes: int) -> list[Bar]:
    if minutes <= 1:
        return [normalize_bar(b) for b in bars if float(b.get("close", 0) or 0) > 0]
    groups: dict[int, Bar] = {}
    seconds = minutes * 60
    for raw in bars:
        bar = normalize_bar(raw)
        if bar["close"] <= 0 or bar["ts"] <= 0:
            continue
        bucket = (bar["ts"] // seconds) * seconds
        if bucket not in groups:
            groups[bucket] = {
                "ts": bucket,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        else:
            row = groups[bucket]
            row["high"] = max(float(row["high"]), bar["high"])
            row["low"] = min(float(row["low"]), bar["low"])
            row["close"] = bar["close"]
            row["volume"] = float(row.get("volume", 0)) + bar["volume"]
    return [groups[k] for k in sorted(groups)]


def _true_ranges(bars: list[Bar]) -> list[float]:
    clean = [normalize_bar(b) for b in bars]
    trs: list[float] = []
    for i in range(1, len(clean)):
        cur = clean[i]
        prev_close = clean[i - 1]["close"]
        trs.append(
            max(
                cur["high"] - cur["low"],
                abs(cur["high"] - prev_close),
                abs(cur["low"] - prev_close),
            )
        )
    return trs


def atr(bars: list[Bar], length: int = 14) -> float | None:
    if length <= 0 or len(bars) < length + 1:
        return None
    trs = _true_ranges(bars)
    if len(trs) < length:
        return None
    return sum(trs[-length:]) / length


def atr_ratio(bars: list[Bar], length: int = 14, baseline: int = 50) -> float | None:
    trs = _true_ranges(bars)
    if len(trs) < baseline:
        return None
    current = sum(trs[-length:]) / length
    base = sum(trs[-baseline:]) / baseline
    if base <= 1e-12:
        return None
    return current / base


def efficiency_ratio(closes: list[float], length: int = 10) -> float | None:
    if length <= 0 or len(closes) < length + 1:
        return None
    window = closes[-(length + 1):]
    direction = abs(window[-1] - window[0])
    noise = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    if noise <= 1e-12:
        return 0.0
    return direction / noise


def round_trip_cost_pct(
    mark: float | None,
    bid: float | None,
    ask: float | None,
    fee_rate: float = 0.0026,
    slippage_bps: float = 5.0,
) -> float:
    spread_pct = 0.0
    if bid and ask and bid > 0 and ask >= bid:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_pct = (ask - bid) / mid * 100
    fee_pct = fee_rate * 2 * 100
    slip_pct = slippage_bps * 2 / 100
    total = fee_pct + slip_pct + spread_pct
    return round(total if isfinite(total) else 0.0, 6)


def trend_breakout_snapshot(
    bars_1m: list[Bar],
    short_len: int = 8,
    long_len: int = 21,
    breakout_bars: int = 20,
    efficiency_min: float = 0.35,
    cost_multiple: float = 1.4,
    compression_max: float = 0.85,
    mark: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    fee_rate: float = 0.0026,
    slippage_bps: float = 5.0,
) -> dict[str, Any]:
    bars5 = resample_bars(bars_1m, 5)
    bars15 = resample_bars(bars_1m, 15)
    required_5 = max(long_len + 2, breakout_bars + 2, 52)
    required_15 = long_len + 2
    cost_pct = round_trip_cost_pct(mark, bid, ask, fee_rate, slippage_bps)
    base = {
        "signal": None,
        "regime": "warming",
        "reason": "warming",
        "cost_pct": cost_pct,
        "bars_1m": len(bars_1m),
        "bars_5m": len(bars5),
        "bars_15m": len(bars15),
    }
    if len(bars5) < required_5 or len(bars15) < required_15:
        return base

    closes5 = [float(b["close"]) for b in bars5]
    closes15 = [float(b["close"]) for b in bars15]
    fast5 = sma(closes5, short_len)
    slow5 = sma(closes5, long_len)
    fast15 = sma(closes15, short_len)
    slow15 = sma(closes15, long_len)
    slow15_prev = sma(closes15[:-1], long_len)
    eff = efficiency_ratio(closes5, 10)
    ratio = atr_ratio(bars5, 14, 50)
    atr_now = atr(bars5, 14)
    atr_prev = atr(bars5[:-1], 14)
    if None in (fast5, slow5, fast15, slow15, slow15_prev, eff):
        return base

    higher_up = fast15 > slow15 and slow15 > slow15_prev
    local_up = fast5 > slow5
    prior = bars5[-(breakout_bars + 1):-1]
    breakout_level = max(float(b["high"]) for b in prior)
    current = float(bars5[-1]["close"])
    breakout = current > breakout_level
    expanding = bool(
        ratio is not None and atr_now is not None and atr_prev is not None
        and (ratio >= 1.0 or atr_now > atr_prev)
    )
    compressed = bool(ratio is not None and ratio < compression_max)

    window = bars5[-(breakout_bars + 1):]
    recent_high = max(float(b["high"]) for b in window)
    recent_low = min(float(b["low"]) for b in window)
    range_pct = ((recent_high - recent_low) / current * 100) if current > 0 else 0.0
    momentum_pct = (
        (current / float(bars5[-4]["close"]) - 1) * 100
        if len(bars5) >= 4 and float(bars5[-4]["close"]) > 0
        else 0.0
    )
    opportunity_pct = max(range_pct, momentum_pct, 0.0)
    hurdle_pct = cost_pct * cost_multiple

    result = {
        **base,
        "regime": "trend" if higher_up and local_up else "nontrend",
        "reason": "ready",
        "fast_5m": round(float(fast5), 6),
        "slow_5m": round(float(slow5), 6),
        "fast_15m": round(float(fast15), 6),
        "slow_15m": round(float(slow15), 6),
        "efficiency": round(float(eff), 6),
        "atr_ratio": None if ratio is None else round(float(ratio), 6),
        "compressed": compressed,
        "expanding": expanding,
        "breakout_level": round(breakout_level, 6),
        "breakout": breakout,
        "range_pct": round(range_pct, 6),
        "momentum_pct": round(momentum_pct, 6),
        "opportunity_pct": round(opportunity_pct, 6),
        "hurdle_pct": round(hurdle_pct, 6),
    }
    if not higher_up:
        result["reason"] = "higher_timeframe_not_up"
    elif not local_up:
        result["reason"] = "local_trend_not_up"
    elif eff < efficiency_min:
        result["regime"] = "chop"
        result["reason"] = "low_efficiency"
    elif ratio is not None and ratio < compression_max and not expanding:
        result["regime"] = "compress"
        result["reason"] = "awaiting_expansion"
    elif not breakout:
        result["reason"] = "no_breakout"
    elif opportunity_pct < hurdle_pct:
        result["reason"] = "edge_below_cost_hurdle"
    else:
        result["signal"] = "buy"
        result["reason"] = "qualified_trend_breakout"
    return result


def trend_exit_signal(
    bars_1m: list[Bar],
    short_len: int = 8,
    long_len: int = 21,
) -> bool:
    bars5 = resample_bars(bars_1m, 5)
    if len(bars5) < long_len + 1:
        return False
    closes = [float(b["close"]) for b in bars5]
    fast = sma(closes, short_len)
    slow = sma(closes, long_len)
    return bool(fast is not None and slow is not None and fast < slow)


def exit_plan(
    bars_1m: list[Bar],
    entry_price: float,
    highest_price: float,
    mark: float,
    configured_stop_pct: float,
    cost_pct: float,
    frozen_hard_stop: float = 0.0,
) -> dict[str, float]:
    """Hard stop is frozen at entry. Trail and breakeven may only rise."""
    atr_value = atr(resample_bars(bars_1m, 5) or bars_1m, 14)
    atr_pct = (atr_value / mark * 100) if atr_value and mark > 0 else 0.0
    initial_stop_pct = max(0.8, min(configured_stop_pct, max(atr_pct * 2.5, cost_pct * 1.25, 0.8)))
    hard_stop = entry_price * (1 - initial_stop_pct / 100)
    if frozen_hard_stop > 0:
        hard_stop = max(hard_stop, frozen_hard_stop)

    gain_pct = ((mark / entry_price) - 1) * 100 if entry_price > 0 else 0.0
    breakeven_trigger_pct = max(0.9, cost_pct * 1.5)
    breakeven_price = entry_price * (1 + max(cost_pct * 0.55, 0.15) / 100)

    trail_activation_pct = max(1.2, cost_pct * 2.0)
    trail_distance_pct = max(0.6, atr_pct * 2.0, cost_pct * 0.9)
    trailing_stop = (
        highest_price * (1 - trail_distance_pct / 100)
        if gain_pct >= trail_activation_pct
        else 0.0
    )

    active_stop = hard_stop
    if gain_pct >= breakeven_trigger_pct:
        active_stop = max(active_stop, breakeven_price)
    if trailing_stop > 0:
        active_stop = max(active_stop, trailing_stop)
    if frozen_hard_stop > 0:
        active_stop = max(active_stop, frozen_hard_stop)

    return {
        "atr_pct": round(atr_pct, 6),
        "initial_stop_pct": round(initial_stop_pct, 6),
        "hard_stop": round(hard_stop, 6),
        "gain_pct": round(gain_pct, 6),
        "breakeven_trigger_pct": round(breakeven_trigger_pct, 6),
        "trail_activation_pct": round(trail_activation_pct, 6),
        "trail_distance_pct": round(trail_distance_pct, 6),
        "active_stop": round(active_stop, 6),
    }
