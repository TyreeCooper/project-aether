"""Asset-class playbooks for the official 12-book Aether desk.

One portfolio philosophy: follow the dominant grain. Each asset gets the
timeframes and session rules appropriate to its market. Paper execution can
route long/short setups across enabled horizons where the product adapter
supports that side. Live execution remains blocked by the runtime boundary.
"""
from __future__ import annotations

from typing import Any

from app.execution_matrix import supported_horizons
from app.strategy import atr, normalize_bar, resample_bars, round_trip_cost_pct, sma

Bar = dict[str, Any]


def _clocks(mode: str) -> list[dict[str, str]]:
    if mode == "daily":
        return [
            {
                "id": "1d",
                "name": "Daily",
                "role": "Signal + bias",
                "plain": "Completed daily candles only. BTC and ETH do not use faster clocks.",
            },
        ]
    if mode == "swing":
        return [
            {
                "id": "1m",
                "name": "1 minute",
                "role": "Tape",
                "plain": "Quote/chart tape only; not a directional signal.",
            },
            {
                "id": "1h",
                "name": "1 hour",
                "role": "Swing trigger",
                "plain": "Completed hourly structure provides the swing entry trigger.",
            },
            {
                "id": "4h",
                "name": "4 hour",
                "role": "Grain",
                "plain": "Defines the intermediate trend the trade must follow.",
            },
            {
                "id": "1d",
                "name": "Daily",
                "role": "Bias",
                "plain": "Defines the structural direction; trades do not fight it.",
            },
        ]
    return [
        {
            "id": "1m",
            "name": "1 minute",
            "role": "Tape",
            "plain": "Quote/chart tape only; not a directional signal.",
        },
        {
            "id": "15m",
            "name": "15 minute",
            "role": "Trigger",
            "plain": "Completed 15-minute continuation breakout is the intraday trigger.",
        },
        {
            "id": "1h",
            "name": "1 hour",
            "role": "Context",
            "plain": "Tactical trend must agree with the higher grain.",
        },
        {
            "id": "4h",
            "name": "4 hour",
            "role": "Grain",
            "plain": "Intermediate structure defines the direction Aether follows.",
        },
        {
            "id": "1d",
            "name": "Daily",
            "role": "Bias",
            "plain": "Structural trend. Intraday trades are blocked when it disagrees.",
        },
    ]


PLAYBOOKS: dict[str, dict[str, Any]] = {
    "eurusd": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "fx",
        "cluster_cap": 2,
        "sessions": {
            "intraday": {"london", "overlap", "ny"},
            "swing": {"london", "overlap", "ny"},
        },
        "min_stop_pct": 0.25,
        "max_stop_pct": 2.0,
        "time_stop_minutes": {"intraday": 360, "swing": 4320},
    },
    "usdjpy": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "fx",
        "cluster_cap": 2,
        "sessions": {
            "intraday": {"asia", "london", "overlap", "ny"},
            "swing": {"asia", "london", "overlap", "ny"},
        },
        "min_stop_pct": 0.25,
        "max_stop_pct": 2.0,
        "time_stop_minutes": {"intraday": 360, "swing": 4320},
    },
    "mes": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "us_equity_beta",
        "cluster_cap": 2,
        "sessions": {"intraday": {"rth"}, "swing": {"rth"}},
        "min_stop_pct": 0.50,
        "max_stop_pct": 3.0,
        "time_stop_minutes": {"intraday": 390, "swing": 4320},
    },
    "mnq": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "us_equity_beta",
        "cluster_cap": 2,
        "sessions": {"intraday": {"rth"}, "swing": {"rth"}},
        "min_stop_pct": 0.65,
        "max_stop_pct": 4.0,
        "time_stop_minutes": {"intraday": 390, "swing": 4320},
    },
    "mgc": {
        "primary": "swing",
        "secondary": "intraday",
        "cluster": "metals",
        "cluster_cap": 1,
        "sessions": {
            "swing": {"globex", "rth"},
            "intraday": {"rth"},
        },
        "min_stop_pct": 0.60,
        "max_stop_pct": 4.0,
        "time_stop_minutes": {"intraday": 390, "swing": 10080},
    },
    "mcl": {
        "primary": "swing",
        "secondary": "intraday",
        "cluster": "energy",
        "cluster_cap": 1,
        "sessions": {
            "swing": {"globex", "rth"},
            "intraday": {"rth"},
        },
        "min_stop_pct": 0.80,
        "max_stop_pct": 5.0,
        "time_stop_minutes": {"intraday": 390, "swing": 10080},
    },
    "us10y": {
        "primary": "swing",
        "secondary": None,
        "cluster": "rates",
        "cluster_cap": 1,
        "sessions": {"swing": {"globex", "rth"}},
        "min_stop_pct": 0.40,
        "max_stop_pct": 3.0,
        "time_stop_minutes": {"swing": 10080},
    },
    "nvda": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "us_equity_beta",
        "cluster_cap": 2,
        "sessions": {"intraday": {"rth"}, "swing": {"rth"}},
        "min_stop_pct": 1.0,
        "max_stop_pct": 6.0,
        "time_stop_minutes": {"intraday": 390, "swing": 4320},
    },
    "tsla": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "us_equity_beta",
        "cluster_cap": 2,
        "sessions": {"intraday": {"rth"}, "swing": {"rth"}},
        "min_stop_pct": 1.25,
        "max_stop_pct": 7.0,
        "time_stop_minutes": {"intraday": 390, "swing": 4320},
    },
    "pltr": {
        "primary": "intraday",
        "secondary": "swing",
        "cluster": "us_equity_beta",
        "cluster_cap": 2,
        "sessions": {"intraday": {"rth"}, "swing": {"rth"}},
        "min_stop_pct": 1.25,
        "max_stop_pct": 7.0,
        "time_stop_minutes": {"intraday": 390, "swing": 4320},
    },
    "btc": {
        "primary": "daily_swing",
        "secondary": None,
        "cluster": "crypto",
        "cluster_cap": 2,
        "sessions": {},
        "min_stop_pct": 2.0,
        "max_stop_pct": 20.0,
        "time_stop_minutes": {"daily_swing": None},
    },
    "eth": {
        "primary": "daily_swing",
        "secondary": None,
        "cluster": "crypto",
        "cluster_cap": 2,
        "sessions": {},
        "min_stop_pct": 2.0,
        "max_stop_pct": 20.0,
        "time_stop_minutes": {"daily_swing": None},
        "rider_of": "btc",
        "requires_btc_long": True,
    },
}


def playbook_profile(asset_id: str) -> dict[str, Any]:
    aid = str(asset_id).lower()
    base = dict(PLAYBOOKS[aid])
    base["sessions"] = {
        str(mode): set(values or set())
        for mode, values in (base.get("sessions") or {}).items()
    }
    base["time_stop_minutes"] = dict(
        base.get("time_stop_minutes") or {}
    )
    if "scalp" in supported_horizons(aid):
        base["sessions"]["scalp"] = set(
            base["sessions"].get("intraday")
            or base["sessions"].get("swing")
            or set()
        )
        base["time_stop_minutes"]["scalp"] = 15
    base["asset_id"] = aid
    base["short_setup_detection"] = aid not in {"btc", "eth"}
    base["paper_long_execution_supported"] = True
    base["paper_short_execution_supported"] = aid not in {"btc", "eth"}
    base["short_execution_supported"] = base["paper_short_execution_supported"]
    base["execution_adapter"] = (
        "crypto_spot"
        if aid in {"btc", "eth"}
        else "equity"
        if aid in {"nvda", "tsla", "pltr"}
        else "fx"
        if aid in {"eurusd", "usdjpy"}
        else "future"
    )
    clock_mode = (
        "daily"
        if base["primary"] == "daily_swing"
        else "swing"
        if base["primary"] == "swing" and not base.get("secondary")
        else "intraday"
    )
    base["clocks"] = _clocks(clock_mode)
    if "scalp" in supported_horizons(aid):
        for row in base["clocks"]:
            if row.get("id") == "1m":
                row["role"] = "Scalp trigger / tape"
                row["plain"] = (
                    "Completed 1-minute continuation breakouts can trigger "
                    "paper scalp entries when higher-timeframe grain agrees."
                )
                break
    return base


def _aggregate_hours(bars: list[Bar], hours: int = 4) -> list[Bar]:
    seconds = max(int(hours), 1) * 3600
    groups: dict[int, Bar] = {}
    for raw in bars:
        bar = normalize_bar(raw)
        if bar["ts"] <= 0 or bar["close"] <= 0:
            continue
        bucket = (int(bar["ts"]) // seconds) * seconds
        if bucket not in groups:
            groups[bucket] = dict(bar)
            groups[bucket]["ts"] = bucket
        else:
            row = groups[bucket]
            row["high"] = max(float(row["high"]), float(bar["high"]))
            row["low"] = min(float(row["low"]), float(bar["low"]))
            row["close"] = float(bar["close"])
            row["volume"] = float(row.get("volume", 0)) + float(
                bar.get("volume", 0)
            )
    return [groups[k] for k in sorted(groups)]


def _direction(bars: list[Bar], fast: int, slow: int) -> str:
    clean = [
        normalize_bar(b)
        for b in bars
        if float(b.get("close", b.get("c", 0)) or 0) > 0
    ]
    closes = [float(b["close"]) for b in clean]
    if len(closes) < slow + 1:
        return "warming"
    fast_now = sma(closes, fast)
    slow_now = sma(closes, slow)
    slow_prev = sma(closes[:-1], slow)
    if None in (fast_now, slow_now, slow_prev):
        return "warming"
    last = closes[-1]
    if (
        last > float(slow_now)
        and float(fast_now) > float(slow_now)
        and float(slow_now) > float(slow_prev)
    ):
        return "long"
    if (
        last < float(slow_now)
        and float(fast_now) < float(slow_now)
        and float(slow_now) < float(slow_prev)
    ):
        return "short"
    return "neutral"


def _breakout_direction(
    bars: list[Bar],
    lookback: int = 20,
) -> str | None:
    clean = [
        normalize_bar(b)
        for b in bars
        if float(b.get("close", b.get("c", 0)) or 0) > 0
    ]
    if len(clean) < lookback + 1:
        return None
    cur = clean[-1]
    prior = clean[-(lookback + 1) : -1]
    if float(cur["close"]) > max(float(b["high"]) for b in prior):
        return "long"
    if float(cur["close"]) < min(float(b["low"]) for b in prior):
        return "short"
    return None


def _session_ok(
    profile: dict[str, Any],
    mode: str,
    active_session_ids: set[str],
) -> bool:
    required = set((profile.get("sessions") or {}).get(mode) or set())
    if not required:
        return True
    return bool(required & set(active_session_ids))


def _opportunity_pct(
    source: list[Bar],
    lookback: int,
) -> float:
    clean = [
        normalize_bar(bar)
        for bar in source
        if float(
            bar.get("close", bar.get("c", 0)) or 0
        ) > 0
    ]
    if not clean:
        return 0.0
    window = clean[-max(int(lookback), 2):]
    current = float(window[-1]["close"])
    if current <= 0:
        return 0.0
    high = max(float(row["high"]) for row in window)
    low = min(float(row["low"]) for row in window)
    return max((high - low) / current * 100.0, 0.0)


def _risk_stop_pct(
    source: list[Bar],
    profile: dict[str, Any],
    cost_pct: float,
) -> float:
    mark = float(source[-1]["close"]) if source else 0.0
    av = atr(source, 14) if len(source) >= 15 else None
    atr_pct = (float(av) / mark * 100) if av and mark > 0 else 0.0
    floor = float(profile["min_stop_pct"])
    ceiling = float(profile["max_stop_pct"])
    return round(
        max(
            floor,
            min(
                ceiling,
                max(atr_pct * 2.0, cost_pct * 1.25, floor),
            ),
        ),
        6,
    )


def _filter_enabled(
    filters: dict[str, bool] | None,
    name: str,
) -> bool:
    if not isinstance(filters, dict):
        return True
    return bool(filters.get(name, True))


def _mode_snapshot(
    mode: str,
    profile: dict[str, Any],
    bars_1m: list[Bar],
    bars_1h: list[Bar],
    bars_1d: list[Bar],
    active_session_ids: set[str],
    cost_pct: float,
    filter_settings: dict[str, bool] | None = None,
) -> dict[str, Any]:
    daily = _direction(bars_1d, 20, 50)
    bars_4h = _aggregate_hours(bars_1h, 4)
    four = _direction(bars_4h, 8, 20)
    hourly = _direction(bars_1h, 8, 20)
    session_ok = _session_ok(profile, mode, active_session_ids)
    session_enabled = _filter_enabled(filter_settings, "session_window")
    alignment_enabled = _filter_enabled(
        filter_settings,
        "higher_timeframe_alignment",
    )
    continuation_enabled = _filter_enabled(
        filter_settings,
        "continuation_trigger",
    )

    if mode == "scalp":
        trigger_bars = [
            normalize_bar(bar)
            for bar in bars_1m
            if float(bar.get("close", bar.get("c", 0)) or 0) > 0
        ]
        trigger = _breakout_direction(trigger_bars, 10)
        grain = (daily, four, hourly)
        aligned = daily == four == hourly and daily in {"long", "short"}
        warm = "warming" in set(grain) or len(trigger_bars) < 11
        qualified_reason = "qualified_scalp_grain"
        continuation_reason = "no_1m_continuation"
        entry_clock = "1m"
        bias_clock = "1d/4h/1h"
        score = (
            (20 if daily in {"long", "short"} else 0)
            + (20 if daily in {"long", "short"} and four == daily else 0)
            + (20 if daily in {"long", "short"} and hourly == daily else 0)
            + (30 if trigger in {"long", "short"} and trigger == daily else 0)
            + (10 if session_ok else 0)
        )
        stop_source = trigger_bars[-60:]
        opportunity_pct = _opportunity_pct(trigger_bars, 10)
        signal_key = (
            f"{mode}:{int(trigger_bars[-1]['ts'])}"
            if trigger_bars
            else None
        )
    elif mode == "intraday":
        trigger_bars = resample_bars(
            bars_1m,
            15,
            require_complete=True,
        )
        trigger = _breakout_direction(trigger_bars, 20)
        grain = (daily, four, hourly)
        aligned = daily == four == hourly and daily in {"long", "short"}
        warm = "warming" in set(grain) or len(trigger_bars) < 21
        qualified_reason = "qualified_intraday_grain"
        continuation_reason = "no_15m_continuation"
        entry_clock = "15m"
        bias_clock = "1d/4h"
        score = (
            (25 if daily in {"long", "short"} else 0)
            + (25 if daily in {"long", "short"} and four == daily else 0)
            + (20 if daily in {"long", "short"} and hourly == daily else 0)
            + (20 if trigger in {"long", "short"} and trigger == daily else 0)
            + (10 if session_ok else 0)
        )
        stop_source = trigger_bars
        opportunity_pct = _opportunity_pct(trigger_bars, 20)
        signal_key = (
            f"{mode}:{int(trigger_bars[-1]['ts'])}"
            if trigger_bars
            else None
        )
    else:
        trigger_bars = [
            normalize_bar(bar)
            for bar in bars_1h
            if float(bar.get("close", bar.get("c", 0)) or 0) > 0
        ]
        trigger = _breakout_direction(trigger_bars, 20)
        grain = (daily, four)
        aligned = daily == four and daily in {"long", "short"}
        warm = "warming" in set(grain) or len(trigger_bars) < 21
        qualified_reason = "qualified_swing_grain"
        continuation_reason = "no_1h_continuation"
        entry_clock = "1h"
        bias_clock = "1d/4h"
        score = (
            (35 if daily in {"long", "short"} else 0)
            + (30 if daily in {"long", "short"} and four == daily else 0)
            + (25 if trigger in {"long", "short"} and trigger == daily else 0)
            + (10 if session_ok else 0)
        )
        stop_source = bars_1h
        opportunity_pct = _opportunity_pct(bars_1h, 20)
        signal_key = (
            f"{mode}:{int(normalize_bar(bars_1h[-1])['ts'])}"
            if bars_1h
            else None
        )

    if alignment_enabled:
        direction = daily if aligned else None
    else:
        direction = (
            trigger
            if trigger in {"long", "short"}
            else daily
            if daily in {"long", "short"}
            else four
            if four in {"long", "short"}
            else hourly
            if hourly in {"long", "short"}
            else None
        )

    continuation_ok = trigger in {"long", "short"} and trigger == direction
    direction_ok = direction in {"long", "short"}

    trace = {
        "data_warmup": "rejected" if warm else "passed",
        "session_window": (
            "bypassed"
            if not session_enabled
            else "passed"
            if session_ok
            else "rejected"
        ),
        "higher_timeframe_alignment": (
            "bypassed"
            if not alignment_enabled
            else "passed"
            if aligned
            else "rejected"
        ),
        "continuation_trigger": (
            "bypassed"
            if not continuation_enabled
            else "passed"
            if continuation_ok
            else "rejected"
        ),
        "direction_required": "passed" if direction_ok else "rejected",
    }

    if warm:
        reason = "warming"
    elif session_enabled and not session_ok:
        reason = "session_closed"
    elif alignment_enabled and not aligned:
        reason = "grain_not_aligned"
    elif continuation_enabled and not continuation_ok:
        reason = continuation_reason
    elif not direction_ok:
        reason = "no_direction"
    else:
        bypassed = any(value == "bypassed" for value in trace.values())
        reason = (
            f"{qualified_reason}_filters_bypassed"
            if bypassed
            else qualified_reason
        )

    qualified = (
        not warm
        and (session_ok or not session_enabled)
        and (aligned or not alignment_enabled)
        and (continuation_ok or not continuation_enabled)
        and direction_ok
    )
    signal = (
        "buy"
        if qualified and direction == "long"
        else "short"
        if qualified and direction == "short"
        else None
    )

    stop_pct = _risk_stop_pct(stop_source, profile, cost_pct)
    return {
        "mode": mode,
        "signal": signal,
        "signal_key": signal_key,
        "reason": reason,
        "direction": direction or "flat",
        "daily_grain": daily,
        "four_hour_grain": four,
        "one_hour_grain": hourly,
        "trigger": trigger,
        "session_ok": session_ok,
        "quality_score": score,
        "risk_stop_pct": stop_pct,
        "opportunity_pct": round(opportunity_pct, 6),
        "entry_clock": entry_clock,
        "bias_clock": bias_clock,
        "filter_trace": trace,
    }


def _crypto_daily(
    asset_id: str,
    profile: dict[str, Any],
    bars_1d: list[Bar],
    *,
    in_position: bool,
    btc_bias_on: bool,
    btc_in_position: bool,
    cost_pct: float,
    filter_settings: dict[str, bool] | None = None,
) -> dict[str, Any]:
    clean = [
        normalize_bar(b)
        for b in bars_1d
        if float(b.get("close", b.get("c", 0)) or 0) > 0
    ]
    base = {
        "mode": "daily_swing",
        "signal": None,
        "executable_signal": None,
        "exit_signal": None,
        "direction": "flat",
        "reason": "warming",
        "quality_score": 0,
        "entry_clock": "1d",
        "bias_clock": "1d",
        "daily_only": True,
        "cost_pct": cost_pct,
        "playbook": profile,
        "signal_key": None,
        "execution_status": "no_trade",
        "short_execution_supported": False,
        "opportunities": [],
        "filter_trace": {
            "data_warmup": "rejected",
            "crypto_breakout_direction": "rejected",
        },
    }
    if len(clean) < 200:
        return base
    closes = [float(b["close"]) for b in clean]
    current = closes[-1]
    ma200 = sma(closes, 200)
    prior20 = closes[-21:-1]
    if ma200 is None or len(prior20) < 20:
        return base

    prior_high = max(prior20)
    prior_low = min(prior20)
    bias_on = current > float(ma200)
    breakout = current > prior_high
    structure_distance = (
        (current - prior_low) / current * 100
        if current > 0
        else 0.0
    )
    av = atr(clean, 14)
    atr_pct = (
        float(av) / current * 100
        if av and current > 0
        else 0.0
    )
    risk_stop = min(
        35.0,
        max(
            2.0,
            structure_distance,
            atr_pct * 2.0,
            cost_pct * 1.25,
        ),
    )

    rider_ok = True
    if profile.get("requires_btc_long"):
        rider_ok = bool(btc_bias_on and btc_in_position)

    trend_enabled = _filter_enabled(filter_settings, "crypto_trend_bias")
    rider_enabled = _filter_enabled(filter_settings, "crypto_btc_rider")
    structure_enabled = _filter_enabled(
        filter_settings,
        "crypto_structure_minimum",
    )

    trace = {
        "data_warmup": "passed",
        "crypto_breakout_direction": "passed" if breakout else "rejected",
        "crypto_trend_bias": (
            "bypassed"
            if not trend_enabled
            else "passed"
            if bias_on
            else "rejected"
        ),
        "crypto_btc_rider": (
            "bypassed"
            if not rider_enabled
            else "passed"
            if rider_ok
            else "rejected"
        ),
        "crypto_structure_minimum": (
            "bypassed"
            if not structure_enabled
            else "passed"
            if structure_distance >= 2.0
            else "rejected"
        ),
        "direction_required": "passed" if breakout else "rejected",
    }

    if not breakout:
        signal = None
        reason = "no_20d_breakout"
    elif trend_enabled and not bias_on:
        signal = None
        reason = "below_200d_sma"
    elif rider_enabled and not rider_ok:
        signal = None
        reason = "btc_rider_gate_closed"
    elif structure_enabled and structure_distance < 2.0:
        signal = None
        reason = "structure_under_2pct"
    else:
        signal = "buy"
        bypassed = any(value == "bypassed" for value in trace.values())
        reason = (
            "qualified_daily_200_20_filters_bypassed"
            if bypassed
            else "qualified_daily_200_20"
        )

    exit_signal = None
    if in_position and (
        current < prior_low
        or (trend_enabled and current < float(ma200))
        or (rider_enabled and not rider_ok)
    ):
        exit_signal = "sell"

    score = (
        (40 if bias_on else 0)
        + (30 if breakout else 0)
        + (20 if structure_distance >= 2.0 else 0)
        + (10 if rider_ok else 0)
    )

    return {
        **base,
        "signal": signal,
        "executable_signal": signal,
        "exit_signal": exit_signal,
        "direction": "long" if breakout else "flat",
        "reason": reason,
        "quality_score": score,
        "risk_stop_pct": round(risk_stop, 6),
        "signal_key": f"daily_swing:{int(clean[-1]['ts'])}",
        "daily_close": round(current, 8),
        "sma_200": round(float(ma200), 8),
        "prior_20d_close_high": round(prior_high, 8),
        "prior_20d_close_low": round(prior_low, 8),
        "structure_distance_pct": round(structure_distance, 6),
        "opportunity_pct": round(structure_distance, 6),
        "atr_14_pct": round(atr_pct, 6),
        "btc_rider_gate_open": rider_ok,
        "filter_trace": trace,
        "execution_status": (
            "paper_long_ready" if signal == "buy" else "no_trade"
        ),
        "opportunities": [
            {
                "mode": "daily_swing",
                "signal": signal,
                "reason": reason,
                "quality_score": score,
            }
        ],
    }


def playbook_snapshot(
    asset_id: str,
    bars_1m: list[Bar],
    bars_1h: list[Bar],
    bars_1d: list[Bar],
    *,
    mark: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    fee_rate: float = 0.0,
    active_session_ids: set[str] | None = None,
    in_position: bool = False,
    btc_bias_on: bool = False,
    btc_in_position: bool = False,
    position_side: str | None = None,
    requested_mode: str | None = None,
    filter_settings: dict[str, bool] | None = None,
) -> dict[str, Any]:
    aid = str(asset_id).lower()
    profile = playbook_profile(aid)
    cost_pct = round_trip_cost_pct(
        mark,
        bid,
        ask,
        fee_rate=fee_rate,
        slippage_bps=5.0,
    )

    if aid in {"btc", "eth"}:
        requested = str(requested_mode or "").lower()
        if requested and requested not in {"swing", "daily_swing"}:
            raise ValueError(
                f"horizon_not_configured_for_asset:{aid}:{requested}"
            )
        return _crypto_daily(
            aid,
            profile,
            bars_1d,
            in_position=in_position,
            btc_bias_on=(
                btc_bias_on
                if aid == "eth"
                else True
            ),
            btc_in_position=(
                btc_in_position
                if aid == "eth"
                else True
            ),
            cost_pct=cost_pct,
            filter_settings=filter_settings,
        )

    active = set(active_session_ids or set())
    if requested_mode is not None:
        requested = str(requested_mode).lower()
        if requested not in set(supported_horizons(aid)):
            raise ValueError(
                f"horizon_not_configured_for_asset:{aid}:{requested}"
            )
        modes = [requested]
    else:
        modes = [profile["primary"]]
        if profile.get("secondary"):
            modes.append(profile["secondary"])

    opportunities = [
        _mode_snapshot(
            mode,
            profile,
            bars_1m,
            bars_1h,
            bars_1d,
            active,
            cost_pct,
            filter_settings,
        )
        for mode in modes
    ]
    selected = next(
        (row for row in opportunities if row.get("signal")),
        opportunities[0],
    )
    signal = selected.get("signal")
    long_adapter_ready = bool(
        profile.get("paper_long_execution_supported")
    )
    short_adapter_ready = bool(
        profile.get("paper_short_execution_supported")
    )
    executable = (
        "buy"
        if signal == "buy" and long_adapter_ready
        else "short"
        if signal == "short" and short_adapter_ready
        else None
    )

    side = str(position_side or "").lower()
    long_flip = (
        selected.get("daily_grain") == "short"
        or selected.get("four_hour_grain") == "short"
        or (
            selected.get("mode") in {"scalp", "intraday"}
            and selected.get("one_hour_grain") == "short"
        )
    )
    short_flip = (
        selected.get("daily_grain") == "long"
        or selected.get("four_hour_grain") == "long"
        or (
            selected.get("mode") in {"scalp", "intraday"}
            and selected.get("one_hour_grain") == "long"
        )
    )
    should_exit = (
        in_position
        and (
            (side in {"", "long"} and long_flip)
            or (side == "short" and short_flip)
        )
    )
    exit_signal = "exit" if should_exit else None

    return {
        **selected,
        "signal": signal,
        "executable_signal": executable,
        "exit_signal": exit_signal,
        "cost_pct": cost_pct,
        "playbook": profile,
        "opportunities": opportunities,
        "short_setup_detected": signal == "short",
        "short_execution_supported": short_adapter_ready,
        "execution_status": (
            "paper_long_ready"
            if executable == "buy"
            else "paper_short_ready"
            if executable == "short"
            else "short_not_supported"
            if signal == "short" and not short_adapter_ready
            else "no_trade"
        ),
    }
