"""Score closed paper trades and rank nearby SMA settings. No live promotion."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.paper_exec import SLIPPAGE_BPS
from app.persist import state_path
from app.strategy import crossover_signal

TAKER_FEE = 0.0026
STARTING = 10_000.0
CHAMPION = {"short_ma": 8, "long_ma": 21, "stop_loss_pct": 2.0}
GRID_SHORT = (6, 8, 10)
GRID_LONG = (18, 21, 26)
GRID_STOP = (1.5, 2.0, 2.5)


def _learn_path() -> Path:
    return state_path().with_name("learn_state.json")


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def load_learn() -> dict[str, Any]:
    path = _learn_path()
    if not path.exists():
        return {
            "champion": dict(CHAMPION),
            "challenger": None,
            "last_review_at": None,
            "history": [],
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"champion": dict(CHAMPION), "challenger": None, "last_review_at": None, "history": []}


def save_learn(payload: dict[str, Any]) -> None:
    path = _learn_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def score_exits(fills: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()
    week_start = today.fromordinal(today.toordinal() - today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    wins = losses = flat = 0
    pnl = daily = weekly = monthly = annual = 0.0
    invert = 0.0
    by_reason: dict[str, int] = {}
    series: list[dict[str, Any]] = []
    last_ts = None
    for fill in sorted(fills, key=lambda x: str(x.get("ts", ""))):
        if str(fill.get("side", "")).lower() != "sell":
            continue
        realized = float(fill.get("realized_pnl_usd") or 0)
        fee = float(fill.get("fee_usd") or 0)
        ts = _parse_ts(fill.get("ts"))
        pnl += realized
        invert += -realized - (2 * fee)
        if ts:
            last_ts = ts
            if ts.date() == today:
                daily += realized
            if ts.date() >= week_start:
                weekly += realized
            if ts.date() >= month_start:
                monthly += realized
            if ts.date() >= year_start:
                annual += realized
            series.append({"ts": ts.isoformat(), "pnl": round(realized, 4), "cum": round(pnl, 4)})
        if realized > 1e-9:
            wins += 1
        elif realized < -1e-9:
            losses += 1
        else:
            flat += 1
        actor = str(fill.get("actor") or "unknown")
        by_reason[actor] = by_reason.get(actor, 0) + 1
    closed = wins + losses + flat
    age = None
    if last_ts:
        age = int((now - last_ts).total_seconds())
    return {
        "closed": closed,
        "wins": wins,
        "losses": losses,
        "breakeven": flat,
        "realized_pnl_usd": round(pnl, 4),
        "daily_pnl_usd": round(daily, 4),
        "weekly_pnl_usd": round(weekly, 4),
        "monthly_pnl_usd": round(monthly, 4),
        "annual_pnl_usd": round(annual, 4),
        "invert_pnl_usd": round(invert, 4),
        "expectancy_usd": round(pnl / closed, 4) if closed else 0.0,
        "win_rate_pct": round(wins / (wins + losses) * 100, 2) if wins + losses else 0.0,
        "exits_by_actor": by_reason,
        "series": series[-60:],
        "last_exit_at": last_ts.isoformat() if last_ts else None,
        "last_exit_age_s": age,
        "as_of": now.isoformat(),
    }


def replay(closes: list[float], short_ma: int, long_ma: int, stop_pct: float) -> dict[str, Any]:
    usd = STARTING
    btc = 0.0
    avg = 0.0
    wins = losses = flat = 0
    pnl = 0.0
    peak = STARTING
    max_dd = 0.0
    trades = 0
    slip = SLIPPAGE_BPS / 10_000.0
    for i in range(len(closes)):
        window = closes[: i + 1]
        px = window[-1]
        equity = usd + btc * px
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        if btc > 0 and avg > 0 and px <= avg * (1 - stop_pct / 100):
            fill = px * (1 - slip)
            fee = fill * btc * TAKER_FEE
            realized = (fill - avg) * btc - fee
            usd += fill * btc - fee
            pnl += realized
            trades += 1
            if realized > 1e-9:
                wins += 1
            elif realized < -1e-9:
                losses += 1
            else:
                flat += 1
            btc = 0.0
            avg = 0.0
            continue
        signal = crossover_signal(window, short_ma, long_ma, in_position=btc > 0)
        if signal == "buy" and btc == 0:
            fill = px * (1 + slip)
            qty = 0.01
            fee = fill * qty * TAKER_FEE
            cost = fill * qty + fee
            if cost <= usd:
                usd -= cost
                avg = (fill * qty + fee) / qty
                btc = qty
        elif signal == "sell" and btc > 0:
            fill = px * (1 - slip)
            fee = fill * btc * TAKER_FEE
            realized = (fill - avg) * btc - fee
            usd += fill * btc - fee
            pnl += realized
            trades += 1
            if realized > 1e-9:
                wins += 1
            elif realized < -1e-9:
                losses += 1
            else:
                flat += 1
            btc = 0.0
            avg = 0.0
    return {
        "short_ma": short_ma,
        "long_ma": long_ma,
        "stop_loss_pct": stop_pct,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "breakeven": flat,
        "pnl_usd": round(pnl, 4),
        "expectancy_usd": round(pnl / trades, 4) if trades else 0.0,
        "max_drawdown_pct": round(max_dd, 4),
    }


def review(closes: list[float], fills: list[dict[str, Any]], champion: dict[str, Any] | None = None) -> dict[str, Any]:
    state = load_learn()
    champ = dict(champion or state.get("champion") or CHAMPION)
    live_score = score_exits(fills)
    mid = max(len(closes) // 2, champ["long_ma"] + 2)
    train, test = closes[:mid], closes[mid:]
    ranked = []
    for short in GRID_SHORT:
        for long in GRID_LONG:
            if short >= long:
                continue
            for stop in GRID_STOP:
                train_res = replay(train, short, long, stop)
                test_res = replay(test, short, long, stop)
                ranked.append({
                    "params": {"short_ma": short, "long_ma": long, "stop_loss_pct": stop},
                    "train_expectancy": train_res["expectancy_usd"],
                    "test_expectancy": test_res["expectancy_usd"],
                    "test_pnl_usd": test_res["pnl_usd"],
                    "test_drawdown_pct": test_res["max_drawdown_pct"],
                    "test_trades": test_res["trades"],
                })
    ranked.sort(key=lambda x: (x["test_expectancy"], x["test_pnl_usd"], -x["test_drawdown_pct"]), reverse=True)
    champ_test = replay(test, int(champ["short_ma"]), int(champ["long_ma"]), float(champ["stop_loss_pct"]))
    best = ranked[0] if ranked else None
    promote = False
    if best and best["test_trades"] >= 2:
        if best["test_expectancy"] > champ_test["expectancy_usd"] + 0.25:
            if best["test_drawdown_pct"] <= champ_test["max_drawdown_pct"] + 1.5:
                promote = True
    challenger = best if promote else None
    invert_note = "Flip book is a check only. Long-only paper stays on."
    if live_score["closed"] and live_score["invert_pnl_usd"] > live_score["realized_pnl_usd"] + 1:
        invert_note = "Opposite side looked better on this sample. Still a note, not a live short."
    report = {
        "champion": champ,
        "champion_replay": champ_test,
        "challenger": None if challenger is None else challenger["params"],
        "challenger_replay": None if challenger is None else challenger,
        "promote_ready": bool(challenger),
        "live_exits": live_score,
        "bars_used": len(closes),
        "candidates": ranked[:5],
        "last_review_at": datetime.now(timezone.utc).isoformat(),
        "note": invert_note,
    }
    state["champion"] = champ
    state["challenger"] = report["challenger"]
    state["last_review_at"] = report["last_review_at"]
    hist = list(state.get("history") or [])
    hist.insert(0, {"at": report["last_review_at"], "promote_ready": report["promote_ready"], "live": live_score})
    state["history"] = hist[:20]
    save_learn(state)
    report["history"] = state["history"]
    return report
