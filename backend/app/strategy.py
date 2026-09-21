"""Trend-aware SMA strategy primitives shared by runtime and replay."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from app.fees import TAKER_FEE as DEFAULT_TAKER_FEE

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


def resample_bars(
    bars: list[Bar],
    minutes: int,
    require_complete: bool = False,
) -> list[Bar]:
    """Aggregate 1m bars onto aligned N-minute boundaries.

    When require_complete=True, partial higher-timeframe buckets are discarded.
    This prevents look-ahead/partial-candle decisions at 5m and 15m boundaries.
    """
    if minutes <= 1:
        return [
            normalize_bar(b)
            for b in bars
            if float(b.get("close", b.get("c", 0)) or 0) > 0
        ]

    groups: dict[int, Bar] = {}
    members: dict[int, set[int]] = {}
    seconds = minutes * 60
    for raw in bars:
        bar = normalize_bar(raw)
        if bar["close"] <= 0 or bar["ts"] <= 0:
            continue
        bucket = (bar["ts"] // seconds) * seconds
        minute_id = bar["ts"] // 60
        members.setdefault(bucket, set()).add(minute_id)
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

    out: list[Bar] = []
    for bucket in sorted(groups):
        if require_complete:
            ids = sorted(members.get(bucket, set()))
            if len(ids) < minutes:
                continue
            if ids[-1] - ids[0] != minutes - 1:
                continue
        out.append(groups[bucket])
    return out

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


def momentum_pct(closes: list[float], bars_back: int) -> float | None:
    if bars_back <= 0 or len(closes) < bars_back + 1:
        return None
    base = float(closes[-(bars_back + 1)])
    if base <= 0:
        return None
    return (float(closes[-1]) / base - 1) * 100


def close_location_value(bar: Bar) -> float | None:
    clean = normalize_bar(bar)
    span = clean["high"] - clean["low"]
    if span <= 1e-12:
        return None
    return (clean["close"] - clean["low"]) / span


def multi_horizon_momentum(closes5: list[float]) -> dict[str, float | int | bool | None]:
    """1h/3h/6h time-series momentum vote on completed 5m closes."""
    m1 = momentum_pct(closes5, 12)
    m3 = momentum_pct(closes5, 36)
    m6 = momentum_pct(closes5, 72)
    vals = [m1, m3, m6]
    available = [v for v in vals if v is not None]
    positive = sum(1 for v in available if float(v) > 0)
    return {
        "momentum_1h_pct": None if m1 is None else round(float(m1), 6),
        "momentum_3h_pct": None if m3 is None else round(float(m3), 6),
        "momentum_6h_pct": None if m6 is None else round(float(m6), 6),
        "momentum_votes": positive,
        "momentum_available": len(available),
        "momentum_confirmed": bool(len(available) >= 2 and positive >= 2),
    }


def risk_capped_qty(
    *,
    equity: float,
    price: float,
    configured_qty: float,
    stop_pct: float,
    cost_pct: float,
    risk_fraction: float = 0.0035,
) -> float:
    """Cap position size so modeled stop+friction loss stays inside risk budget.

    This never increases the configured quantity; it only reduces it.
    """
    if equity <= 0 or price <= 0 or configured_qty <= 0 or risk_fraction <= 0:
        return 0.0
    loss_fraction = max((max(stop_pct, 0.0) + max(cost_pct, 0.0)) / 100, 1e-6)
    risk_budget = equity * risk_fraction
    max_notional = risk_budget / loss_fraction
    qty = min(configured_qty, max_notional / price)
    return round(max(qty, 0.0), 8)


def round_trip_cost_pct(
    mark: float | None,
    bid: float | None,
    ask: float | None,
    fee_rate: float = DEFAULT_TAKER_FEE,
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
    breakout_atr_min: float = 0.05,
    close_location_min: float = 0.65,
    shock_atr_max: float = 3.0,
    stop_loss_pct: float = 2.0,
    mark: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    fee_rate: float = DEFAULT_TAKER_FEE,
    slippage_bps: float = 5.0,
) -> dict[str, Any]:
    """Cost-aware, multi-timeframe long breakout using completed bars only."""
    bars5 = resample_bars(bars_1m, 5, require_complete=True)
    bars15 = resample_bars(bars_1m, 15, require_complete=True)
    required_5 = max(long_len + 2, breakout_bars + 2, 73)
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
    if None in (fast5, slow5, fast15, slow15, slow15_prev, eff, atr_now):
        return base

    current_bar = bars5[-1]
    current = float(current_bar["close"])
    higher_up = fast15 > slow15 and slow15 > slow15_prev
    local_up = fast5 > slow5

    prior = bars5[-(breakout_bars + 1):-1]
    breakout_level = max(float(b["high"]) for b in prior)
    breakout = current > breakout_level
    breakout_strength_atr = (
        max(current - breakout_level, 0.0) / float(atr_now)
        if float(atr_now) > 1e-12
        else 0.0
    )

    expanding = bool(
        ratio is not None
        and atr_prev is not None
        and (ratio >= 1.0 or float(atr_now) > float(atr_prev))
    )
    compressed = bool(ratio is not None and ratio < compression_max)

    window = bars5[-(breakout_bars + 1):]
    recent_high = max(float(b["high"]) for b in window)
    recent_low = min(float(b["low"]) for b in window)
    range_pct = ((recent_high - recent_low) / current * 100) if current > 0 else 0.0
    cost_coverage = range_pct / cost_pct if cost_pct > 1e-12 else 999.0

    mom = multi_horizon_momentum(closes5)
    clv = close_location_value(current_bar)
    bar_range = float(current_bar["high"]) - float(current_bar["low"])
    bar_range_atr = bar_range / float(atr_now) if float(atr_now) > 1e-12 else 0.0
    atr_pct = float(atr_now) / current * 100 if current > 0 else 0.0
    suggested_stop_pct = max(
        0.8,
        min(stop_loss_pct, max(atr_pct * 2.5, cost_pct * 1.25, 0.8)),
    )

    quality_score = 0
    quality_score += 20 if higher_up else 0
    quality_score += 15 if local_up else 0
    quality_score += 15 if float(eff) >= efficiency_min else 0
    quality_score += 15 if mom["momentum_confirmed"] else 0
    quality_score += 10 if expanding else 0
    quality_score += 10 if breakout_strength_atr >= breakout_atr_min else 0
    quality_score += 5 if clv is not None and clv >= close_location_min else 0
    quality_score += 10 if cost_coverage >= cost_multiple else 0

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
        "atr_pct": round(atr_pct, 6),
        "compressed": compressed,
        "expanding": expanding,
        "breakout_level": round(breakout_level, 6),
        "breakout": breakout,
        "breakout_strength_atr": round(breakout_strength_atr, 6),
        "close_location": None if clv is None else round(float(clv), 6),
        "bar_range_atr": round(bar_range_atr, 6),
        "range_pct": round(range_pct, 6),
        "opportunity_pct": round(range_pct, 6),
        "range_capacity_pct": round(range_pct, 6),
        "cost_coverage": round(cost_coverage, 6),
        "hurdle_pct": round(cost_pct * cost_multiple, 6),
        "suggested_initial_stop_pct": round(suggested_stop_pct, 6),
        "quality_score": quality_score,
        **mom,
    }

    if not higher_up:
        result["reason"] = "higher_timeframe_not_up"
    elif not local_up:
        result["reason"] = "local_trend_not_up"
    elif float(eff) < efficiency_min:
        result["regime"] = "chop"
        result["reason"] = "low_efficiency"
    elif not bool(mom["momentum_confirmed"]):
        result["reason"] = "momentum_not_confirmed"
    elif ratio is not None and ratio < compression_max and not expanding:
        result["regime"] = "compress"
        result["reason"] = "awaiting_expansion"
    elif not breakout:
        result["reason"] = "no_breakout"
    elif breakout_strength_atr < breakout_atr_min:
        result["reason"] = "weak_breakout"
    elif clv is None or clv < close_location_min:
        result["reason"] = "weak_close"
    elif bar_range_atr > shock_atr_max:
        result["regime"] = "shock"
        result["reason"] = "volatility_exhaustion"
    elif cost_coverage < cost_multiple:
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
    """Confirmed trend failure on completed 5m bars, not a single noisy cross."""
    bars5 = resample_bars(bars_1m, 5, require_complete=True)
    if len(bars5) < long_len + 3:
        return False
    closes = [float(b["close"]) for b in bars5]
    fast = sma(closes, short_len)
    slow = sma(closes, long_len)
    slow_prev = sma(closes[:-2], long_len)
    if None in (fast, slow, slow_prev):
        return False
    below_slow = closes[-1] < float(slow) and closes[-2] < float(slow)
    trend_rolled = float(fast) < float(slow) and float(slow) <= float(slow_prev)
    return bool(below_slow and trend_rolled)

def exit_plan(
    bars_1m: list[Bar],
    entry_price: float,
    highest_price: float,
    mark: float,
    configured_stop_pct: float,
    cost_pct: float,
    frozen_hard_stop: float = 0.0,
) -> dict[str, float]:
    """ATR + structure initial risk, then breakeven and Chandelier-style trail."""
    bars5 = resample_bars(bars_1m, 5, require_complete=True)
    source = bars5 or bars_1m
    atr_value = atr(source, 14)
    atr_pct = (atr_value / mark * 100) if atr_value and mark > 0 else 0.0

    initial_stop_pct = max(
        0.8,
        min(
            configured_stop_pct,
            max(atr_pct * 2.5, cost_pct * 1.25, 0.8),
        ),
    )
    atr_stop = entry_price * (1 - initial_stop_pct / 100)

    structural_stop = 0.0
    if atr_value and len(bars5) >= 10:
        swing_low = min(float(b["low"]) for b in bars5[-10:])
        candidate = swing_low - float(atr_value) * 0.25
        if 0 < candidate < entry_price:
            structural_stop = candidate

    hard_stop = max(atr_stop, structural_stop)
    if frozen_hard_stop > 0:
        hard_stop = max(hard_stop, frozen_hard_stop)

    gain_pct = ((mark / entry_price) - 1) * 100 if entry_price > 0 else 0.0
    breakeven_trigger_pct = max(1.0, cost_pct * 1.35)
    breakeven_price = entry_price * (1 + max(cost_pct * 0.60, 0.20) / 100)

    trail_activation_pct = max(1.5, cost_pct * 1.75)
    chandelier_stop = 0.0
    trail_distance_pct = 0.0
    if atr_value and mark > 0:
        trail_distance = max(float(atr_value) * 3.0, highest_price * cost_pct / 100)
        trail_distance_pct = trail_distance / highest_price * 100 if highest_price > 0 else 0.0
        if gain_pct >= trail_activation_pct:
            chandelier_stop = highest_price - trail_distance

    active_stop = hard_stop
    if gain_pct >= breakeven_trigger_pct:
        active_stop = max(active_stop, breakeven_price)
    if chandelier_stop > 0:
        active_stop = max(active_stop, chandelier_stop)
    if frozen_hard_stop > 0:
        active_stop = max(active_stop, frozen_hard_stop)

    return {
        "atr_pct": round(atr_pct, 6),
        "initial_stop_pct": round(initial_stop_pct, 6),
        "atr_stop": round(atr_stop, 6),
        "structural_stop": round(structural_stop, 6),
        "hard_stop": round(hard_stop, 6),
        "gain_pct": round(gain_pct, 6),
        "breakeven_trigger_pct": round(breakeven_trigger_pct, 6),
        "trail_activation_pct": round(trail_activation_pct, 6),
        "trail_distance_pct": round(trail_distance_pct, 6),
        "chandelier_stop": round(chandelier_stop, 6),
        "active_stop": round(active_stop, 6),
    }
