"""Walk-forward review for the same trend/cost model used by the paper runtime."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.clock import allow_after_losses
from app.paper_exec import SLIPPAGE_BPS
from app.persist import state_path
from app.performance import summarize_backtest
from app.strategy import exit_plan, risk_capped_qty, trend_breakout_snapshot, trend_exit_signal

TAKER_FEE = float(os.getenv("AETHER_TAKER_FEE_RATE", "0.008"))
STARTING = 10_000.0
MIN_OOS_TRADES = 12
CHAMPION = {
    "short_ma": 8,
    "long_ma": 21,
    "stop_loss_pct": 2.0,
    "breakout_bars": 20,
    "efficiency_min": 0.35,
    "cost_multiple": 1.4,
}
CANDIDATES = (
    {"short_ma": 6, "long_ma": 18, "stop_loss_pct": 1.8, "breakout_bars": 15, "efficiency_min": 0.30, "cost_multiple": 1.35},
    {"short_ma": 8, "long_ma": 21, "stop_loss_pct": 2.0, "breakout_bars": 20, "efficiency_min": 0.35, "cost_multiple": 1.40},
    {"short_ma": 10, "long_ma": 30, "stop_loss_pct": 2.2, "breakout_bars": 20, "efficiency_min": 0.40, "cost_multiple": 1.50},
    {"short_ma": 12, "long_ma": 36, "stop_loss_pct": 2.5, "breakout_bars": 30, "efficiency_min": 0.45, "cost_multiple": 1.60},
)
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
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("champion"), dict):
            data["champion"] = dict(CHAMPION)
        return data
    except (OSError, json.JSONDecodeError):
        return {
            "champion": dict(CHAMPION),
            "challenger": None,
            "last_review_at": None,
            "history": [],
        }


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
    by_reason: dict[str, int] = {}
    series: list[dict[str, Any]] = []
    last_ts = None
    for fill in sorted(fills, key=lambda x: str(x.get("ts", ""))):
        if str(fill.get("side", "")).lower() != "sell":
            continue
        realized = float(fill.get("realized_pnl_usd") or 0)
        ts = _parse_ts(fill.get("ts"))
        pnl += realized
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
            series.append(
                {"ts": ts.isoformat(), "pnl": round(realized, 4), "cum": round(pnl, 4)}
            )
        if realized > 1e-9:
            wins += 1
        elif realized < -1e-9:
            losses += 1
        else:
            flat += 1
        actor = str(fill.get("actor") or "unknown")
        by_reason[actor] = by_reason.get(actor, 0) + 1
    closed = wins + losses + flat
    age = int((now - last_ts).total_seconds()) if last_ts else None
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
        "expectancy_usd": round(pnl / closed, 4) if closed else 0.0,
        "win_rate_pct": round(wins / (wins + losses) * 100, 2)
        if wins + losses
        else 0.0,
        "exits_by_actor": by_reason,
        "series": series[-60:],
        "last_exit_at": last_ts.isoformat() if last_ts else None,
        "last_exit_age_s": age,
        "as_of": now.isoformat(),
    }


def replay(
    bars: list[dict[str, Any]],
    config: dict[str, Any],
    detailed: bool = False,
    start_index: int = 330,
) -> dict[str, Any]:
    if len(bars) < 720:
        return {
            **config,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "pnl_usd": 0.0,
            "expectancy_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "insufficient_history": True,
            "summary": summarize_backtest([], [], STARTING),
            "trade_log": [] if detailed else None,
        }

    usd = STARTING
    btc = 0.0
    avg = 0.0
    highest = 0.0
    position_stop = 0.0
    entry_i: int | None = None
    wins = losses = flat = 0
    consecutive_losses = 0
    pnl = 0.0
    peak = STARTING
    max_dd = 0.0
    trades = 0
    cooldown_until_i = 0
    slip = SLIPPAGE_BPS / 10_000.0
    trade_log: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    entry_price = 0.0
    entry_ts: Any = None
    trade_low = 0.0
    trade_high = 0.0
    last_entry_bucket: int | None = None

    first_i = max(330, int(start_index))
    for i in range(first_i, len(bars)):
        history = bars[max(0, i - 1439) : i + 1]
        px = float(bars[i]["close"])
        equity = usd + btc * px
        equity_curve.append({"ts": bars[i]["ts"], "equity": equity})
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

        if btc > 0:
            highest = max(highest, px)
            trade_low = min(
                trade_low or float(bars[i]["low"]),
                float(bars[i]["low"]),
            )
            trade_high = max(
                trade_high or float(bars[i]["high"]),
                float(bars[i]["high"]),
            )
            cost_pct = TAKER_FEE * 2 * 100 + SLIPPAGE_BPS * 2 / 100
            plan = exit_plan(
                history,
                avg,
                highest,
                px,
                float(config["stop_loss_pct"]),
                cost_pct,
                frozen_hard_stop=position_stop,
            )
            position_stop = max(position_stop, float(plan["active_stop"]))
            timed_out = entry_i is not None and i - entry_i >= 180
            trend_failed = trend_exit_signal(
                history,
                int(config["short_ma"]),
                int(config["long_ma"]),
            )
            stop_hit = float(bars[i]["low"]) <= position_stop
            if stop_hit or trend_failed or timed_out:
                raw_exit = position_stop if stop_hit else px
                fill = raw_exit * (1 - slip)
                fee = fill * btc * TAKER_FEE
                realized = (fill - avg) * btc - fee
                usd += fill * btc - fee
                pnl += realized
                trades += 1
                trade_log.append(
                    {
                        "entry_ts": entry_ts,
                        "exit_ts": bars[i]["ts"],
                        "entry_price": entry_price,
                        "exit_price": fill,
                        "pnl_usd": realized,
                        "mae_pct": (
                            (trade_low / entry_price - 1) * 100
                            if entry_price > 0 and trade_low > 0
                            else 0.0
                        ),
                        "mfe_pct": (
                            (trade_high / entry_price - 1) * 100
                            if entry_price > 0 and trade_high > 0
                            else 0.0
                        ),
                        "exit_reason": (
                            "stop"
                            if stop_hit
                            else "trend_failure"
                            if trend_failed
                            else "time_stop"
                        ),
                    }
                )
                if realized > 1e-9:
                    wins += 1
                    consecutive_losses = 0
                elif realized < -1e-9:
                    losses += 1
                    consecutive_losses += 1
                else:
                    flat += 1
                btc = 0.0
                avg = 0.0
                highest = 0.0
                position_stop = 0.0
                entry_i = None
                entry_price = 0.0
                entry_ts = None
                trade_low = 0.0
                trade_high = 0.0
                cooldown_until_i = i + (30 if consecutive_losses >= 2 else 15)
            continue

        bucket = int(bars[i]["ts"]) // 300
        if last_entry_bucket == bucket:
            continue
        last_entry_bucket = bucket

        if i < cooldown_until_i:
            continue
        if not allow_after_losses(history, consecutive_losses):
            continue

        snap = trend_breakout_snapshot(
            history,
            short_len=int(config["short_ma"]),
            long_len=int(config["long_ma"]),
            breakout_bars=int(config["breakout_bars"]),
            efficiency_min=float(config["efficiency_min"]),
            cost_multiple=float(config["cost_multiple"]),
            stop_loss_pct=float(config["stop_loss_pct"]),
            mark=px,
            bid=px * 0.9999,
            ask=px * 1.0001,
            fee_rate=TAKER_FEE,
            slippage_bps=SLIPPAGE_BPS,
        )
        if snap.get("signal") != "buy":
            continue

        fill = px * (1 + slip)
        fee_pct = TAKER_FEE * 2 * 100 + SLIPPAGE_BPS * 2 / 100
        qty = risk_capped_qty(
            equity=equity,
            price=fill,
            configured_qty=0.01,
            stop_pct=float(
                snap.get("suggested_initial_stop_pct")
                or config["stop_loss_pct"]
            ),
            cost_pct=fee_pct,
        )
        if qty <= 0:
            continue
        fee = fill * qty * TAKER_FEE
        cost = fill * qty + fee
        if cost <= usd:
            usd -= cost
            avg = (fill * qty + fee) / qty
            btc = qty
            highest = px
            entry_i = i
            entry_price = avg
            entry_ts = bars[i]["ts"]
            trade_low = float(bars[i]["low"])
            trade_high = float(bars[i]["high"])
            plan = exit_plan(
                history,
                avg,
                highest,
                px,
                float(config["stop_loss_pct"]),
                fee_pct,
            )
            position_stop = float(plan["active_stop"])

    summary = summarize_backtest(trade_log, equity_curve, STARTING)
    return {
        **config,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "breakeven": flat,
        "pnl_usd": round(pnl, 4),
        "expectancy_usd": round(pnl / trades, 4) if trades else 0.0,
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "profit_factor": summary["profit_factor"],
        "payoff_ratio": summary["payoff_ratio"],
        "avg_mae_pct": summary["avg_mae_pct"],
        "avg_mfe_pct": summary["avg_mfe_pct"],
        "sharpe_365": summary["sharpe_365"],
        "sortino_365": summary["sortino_365"],
        "insufficient_history": False,
        "summary": summary,
        "trade_log": trade_log if detailed else None,
    }

def review(
    bars: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    champion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_learn()
    champ = dict(CHAMPION)
    champ.update(champion or state.get("champion") or {})
    live_score = score_exits(fills)

    split = max(len(bars) // 2, 720)
    train = bars[:split]
    test = bars[split:]
    ranked: list[dict[str, Any]] = []
    for config in CANDIDATES:
        train_res = replay(train, dict(config))
        test_res = replay(test, dict(config))
        ranked.append(
            {
                "params": dict(config),
                "train_expectancy": train_res["expectancy_usd"],
                "test_expectancy": test_res["expectancy_usd"],
                "test_pnl_usd": test_res["pnl_usd"],
                "test_drawdown_pct": test_res["max_drawdown_pct"],
                "test_trades": test_res["trades"],
            }
        )

    ranked.sort(
        key=lambda x: (
            x["test_expectancy"],
            x["test_pnl_usd"],
            -x["test_drawdown_pct"],
        ),
        reverse=True,
    )
    champ_test = replay(test, champ)
    best = ranked[0] if ranked else None
    challenger = None
    if best and best["test_trades"] >= MIN_OOS_TRADES:
        if best["test_expectancy"] > champ_test["expectancy_usd"] + 0.25:
            if best["test_drawdown_pct"] <= champ_test["max_drawdown_pct"] + 1.0:
                challenger = best

    report = {
        "champion": champ,
        "champion_replay": champ_test,
        "challenger": None if challenger is None else challenger["params"],
        "challenger_replay": challenger,
        "promote_ready": bool(challenger),
        "live_exits": live_score,
        "bars_used": len(bars),
        "history_warning": (
            None if len(bars) >= 1440
            else "Short research window: do not treat challenger performance as proof of profitability."
        ),
        "candidates": ranked[:5],
        "last_review_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Walk-forward paper review only. Runtime and replay share the same "
            "trend, cost-hurdle and managed-exit primitives. No automatic promotion."
        ),
    }
    state["champion"] = champ
    state["challenger"] = report["challenger"]
    state["last_review_at"] = report["last_review_at"]
    hist = list(state.get("history") or [])
    hist.insert(
        0,
        {
            "at": report["last_review_at"],
            "promote_ready": report["promote_ready"],
            "live": live_score,
        },
    )
    state["history"] = hist[:20]
    save_learn(state)
    report["history"] = state["history"]
    return report
