"""Backtest performance statistics with crypto-appropriate daily annualization."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Any


def _date_key(ts: int | float | str | datetime) -> str:
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return str(ts)
    else:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def max_drawdown_pct(equity_curve: list[dict[str, Any]]) -> float:
    peak = 0.0
    worst = 0.0
    for row in equity_curve:
        eq = float(row.get("equity", 0) or 0)
        peak = max(peak, eq)
        if peak > 0:
            worst = max(worst, (peak - eq) / peak * 100)
    return round(worst, 6)


def daily_returns(equity_curve: list[dict[str, Any]]) -> list[float]:
    daily: OrderedDict[str, float] = OrderedDict()
    for row in equity_curve:
        if "ts" not in row:
            continue
        daily[_date_key(row["ts"])] = float(row.get("equity", 0) or 0)
    values = list(daily.values())
    out: list[float] = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            out.append(values[i] / values[i - 1] - 1)
    return out


def annualized_sharpe(equity_curve: list[dict[str, Any]]) -> float | None:
    returns = daily_returns(equity_curve)
    if len(returns) < 3:
        return None
    vol = pstdev(returns)
    if vol <= 1e-12:
        return None
    return round(mean(returns) / vol * sqrt(365), 6)


def annualized_sortino(equity_curve: list[dict[str, Any]]) -> float | None:
    returns = daily_returns(equity_curve)
    if len(returns) < 3:
        return None
    downside = [min(r, 0.0) for r in returns]
    downside_dev = sqrt(sum(r * r for r in downside) / len(downside))
    if downside_dev <= 1e-12:
        return None
    return round(mean(returns) / downside_dev * sqrt(365), 6)


def summarize_backtest(
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    starting_equity: float,
) -> dict[str, Any]:
    pnls = [float(t.get("pnl_usd", 0) or 0) for t in trades]
    wins = [x for x in pnls if x > 1e-9]
    losses = [x for x in pnls if x < -1e-9]
    flats = [x for x in pnls if abs(x) <= 1e-9]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    ending = (
        float(equity_curve[-1]["equity"])
        if equity_curve
        else float(starting_equity)
    )
    avg_win = mean(wins) if wins else 0.0
    avg_loss = abs(mean(losses)) if losses else 0.0
    mae = [float(t.get("mae_pct", 0) or 0) for t in trades]
    mfe = [float(t.get("mfe_pct", 0) or 0) for t in trades]
    closed = len(trades)
    return {
        "starting_equity": round(starting_equity, 4),
        "ending_equity": round(ending, 4),
        "net_pnl_usd": round(ending - starting_equity, 4),
        "return_pct": round(
            ((ending / starting_equity) - 1) * 100 if starting_equity > 0 else 0.0,
            6,
        ),
        "trades": closed,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(flats),
        "win_rate_pct": round(len(wins) / closed * 100, 4) if closed else 0.0,
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "profit_factor": (
            round(gross_profit / gross_loss, 6) if gross_loss > 1e-12 else None
        ),
        "avg_winner_usd": round(avg_win, 4),
        "avg_loser_usd": round(avg_loss, 4),
        "payoff_ratio": (
            round(avg_win / avg_loss, 6) if avg_loss > 1e-12 else None
        ),
        "expectancy_usd": round(sum(pnls) / closed, 4) if closed else 0.0,
        "avg_mae_pct": round(mean(mae), 6) if mae else 0.0,
        "avg_mfe_pct": round(mean(mfe), 6) if mfe else 0.0,
        "max_drawdown_pct": max_drawdown_pct(equity_curve),
        "sharpe_365": annualized_sharpe(equity_curve),
        "sortino_365": annualized_sortino(equity_curve),
    }
