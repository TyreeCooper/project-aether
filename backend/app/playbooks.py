"""Asset-class playbooks for the official 12-book Aether desk.

One portfolio philosophy: follow the dominant grain. Each asset gets the
timeframes and session rules appropriate to its market. The current execution
layer is long-only; short setups are detected and exposed but not fabricated
as executable trades.
"""
from __future__ import annotations

from typing import Any

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


def _mode_snapshot(
    mode: str,
    profile: dict[str, Any],
    bars_1m: list[Bar],
    bars_1h: list[Bar],
    bars_1d: list[Bar],
    active_session_ids: set[str],
    cost_pct: float,
) -> dict[str, Any]:
    daily = _direction(bars_1d, 20, 50)
    bars_4h = _aggregate_hours(bars_1h, 4)
    four = _direction(bars_4h, 8, 20)
    hourly = _direction(bars_1h, 8, 20)
    session_ok = _session_ok(profile, mode, active_session_ids)

    if mode == "intraday":
        trigger_bars = resample_bars(
            bars_1m,
            15,
            require_complete=True,
        )
        trigger = _breakout_direction(trigger_bars, 20)
        aligned = (
            daily == four == hourly
            and daily in {"long", "short"}
        )
        direction = daily if aligned else None
        score = (
            (25 if daily in {"long", "short"} else 0)
            + (25 if direction and four == direction else 0)
            + (20 if direction and hourly == direction else 0)
            + (20 if direction and trigger == direction else 0)
            + (10 if session_ok else 0)
        )
        if (
            "warming" in {daily, four, hourly}
            or len(trigger_bars) < 21
        ):
            reason = "warming"
        elif not session_ok:
            reason = "session_closed"
        elif not aligned:
            reason = "grain_not_aligned"
        elif trigger != direction:
            reason = "no_15m_continuation"
        else:
            reason = "qualified_intraday_grain"
        signal = (
            "buy"
            if direction == "long"
            and reason == "qualified_intraday_grain"
            else "short"
            if direction == "short"
            and reason == "qualified_intraday_grain"
            else None
        )
        stop_pct = _risk_stop_pct(
            trigger_bars,
            profile,
            cost_pct,
        )
        signal_key = (
            f"{mode}:{int(trigger_bars[-1]['ts'])}"
            if trigger_bars
            else None
        )
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
            "entry_clock": "15m",
            "bias_clock": "1d/4h",
        }

    trigger = _breakout_direction(bars_1h, 20)
    aligned = daily == four and daily in {"long", "short"}
    direction = daily if aligned else None
    score = (
        (35 if daily in {"long", "short"} else 0)
        + (30 if direction and four == direction else 0)
        + (25 if direction and trigger == direction else 0)
        + (10 if session_ok else 0)
    )
    if "warming" in {daily, four} or len(bars_1h) < 21:
        reason = "warming"
    elif not session_ok:
        reason = "session_closed"
    elif not aligned:
        reason = "grain_not_aligned"
    elif trigger != direction:
        reason = "no_1h_continuation"
    else:
        reason = "qualified_swing_grain"
    signal = (
        "buy"
        if direction == "long" and reason == "qualified_swing_grain"
        else "short"
        if direction == "short" and reason == "qualified_swing_grain"
        else None
    )
    stop_pct = _risk_stop_pct(
        bars_1h,
        profile,
        cost_pct,
    )
    signal_key = (
        f"{mode}:{int(normalize_bar(bars_1h[-1])['ts'])}"
        if bars_1h
        else None
    )
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
        "entry_clock": "1h",
        "bias_clock": "1d/4h",
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

    signal = None
    reason = "no_20d_breakout"
    if not bias_on:
        reason = "below_200d_sma"
    elif not rider_ok:
        reason = "btc_rider_gate_closed"
    elif structure_distance < 2.0:
        reason = "structure_under_2pct"
    elif breakout:
        signal = "buy"
        reason = "qualified_daily_200_20"

    exit_signal = None
    if in_position and (
        current < prior_low
        or current < float(ma200)
        or not rider_ok
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
        "direction": "long" if bias_on else "flat",
        "reason": reason,
        "quality_score": score,
        "risk_stop_pct": round(risk_stop, 6),
        "signal_key": f"daily_swing:{int(clean[-1]['ts'])}",
        "daily_close": round(current, 8),
        "sma_200": round(float(ma200), 8),
        "prior_20d_close_high": round(prior_high, 8),
        "prior_20d_close_low": round(prior_low, 8),
        "structure_distance_pct": round(
            structure_distance,
            6,
        ),
        "atr_14_pct": round(atr_pct, 6),
        "btc_rider_gate_open": rider_ok,
        "execution_status": (
            "paper_long_ready"
            if signal == "buy"
            else "no_trade"
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
        )

    active = set(active_session_ids or set())
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
            selected.get("mode") == "intraday"
            and selected.get("one_hour_grain") == "short"
        )
    )
    short_flip = (
        selected.get("daily_grain") == "long"
        or selected.get("four_hour_grain") == "long"
        or (
            selected.get("mode") == "intraday"
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
