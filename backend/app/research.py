"""Offline strategy research: long-history fetch, benchmarks, and walk-forward tests."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.learn import CHAMPION, STARTING, TAKER_FEE, replay
from app.paper_exec import SLIPPAGE_BPS
from app.performance import summarize_backtest
from app.strategy import resample_bars, sma

BINANCE_US_KLINES = "https://api.binance.us/api/v3/klines"
MAX_KLINES = 1000

# Small, pre-declared horizon family. This is diagnostic only; no automatic
# promotion is allowed. Longer horizons test whether Tier-1 friction makes the
# existing 5m/3h book structurally too short-lived.
RESEARCH_CANDIDATES = (
    (
        "champion-3h",
        {
            **CHAMPION,
            "time_stop_bars": 180,
        },
    ),
    (
        "swing-6h",
        {
            "short_ma": 12,
            "long_ma": 36,
            "stop_loss_pct": 2.5,
            "breakout_bars": 48,
            "efficiency_min": 0.35,
            "cost_multiple": 1.30,
            "time_stop_bars": 360,
        },
    ),
    (
        "swing-12h",
        {
            "short_ma": 20,
            "long_ma": 50,
            "stop_loss_pct": 3.0,
            "breakout_bars": 72,
            "efficiency_min": 0.30,
            "cost_multiple": 1.25,
            "time_stop_bars": 720,
        },
    ),
    (
        "swing-24h",
        {
            "short_ma": 24,
            "long_ma": 72,
            "stop_loss_pct": 3.5,
            "breakout_bars": 96,
            "efficiency_min": 0.30,
            "cost_multiple": 1.20,
            "time_stop_bars": 1440,
        },
    ),
)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def parse_binance_klines(rows: list[list[Any]]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for row in rows:
        try:
            bars.append(
                {
                    "ts": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return bars


async def fetch_binance_history(
    *,
    symbol: str = "BTCUSD",
    days: int = 30,
    interval: str = "1m",
) -> list[dict[str, Any]]:
    """Fetch paginated public Binance.US candles. Intended for offline research only."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, int(days)))
    cursor = _ms(start)
    end_ms = _ms(end)
    bars: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        while cursor < end_ms:
            response = await client.get(
                BINANCE_US_KLINES,
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": MAX_KLINES,
                },
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                break
            batch = parse_binance_klines(rows)
            if not batch:
                break
            bars.extend(batch)
            next_cursor = int(rows[-1][0]) + 60_000
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            await asyncio.sleep(0.06)

    dedup = {int(b["ts"]): b for b in bars}
    ordered = [dedup[k] for k in sorted(dedup)]

    # Retry any observed missing minute ranges once. If the venue still omits a
    # candle, leave the gap intact so validate_bars() fails the evidence gate.
    gaps = [
        (int(a["ts"]), int(b["ts"]))
        for a, b in zip(ordered, ordered[1:])
        if int(b["ts"]) - int(a["ts"]) > 60
    ]
    if gaps:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for after_s, before_s in gaps[:20]:
                missing = max((before_s - after_s) // 60 - 1, 0)
                if missing <= 0 or missing > MAX_KLINES:
                    continue
                response = await client.get(
                    BINANCE_US_KLINES,
                    params={
                        "symbol": symbol.upper(),
                        "interval": interval,
                        "startTime": (after_s + 60) * 1000,
                        "endTime": (before_s - 60) * 1000,
                        "limit": min(missing, MAX_KLINES),
                    },
                )
                response.raise_for_status()
                rows = response.json()
                if isinstance(rows, list):
                    for bar in parse_binance_klines(rows):
                        dedup[int(bar["ts"])] = bar
                await asyncio.sleep(0.06)

    return [dedup[k] for k in sorted(dedup)]


def validate_bars(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if not bars:
        return {"ok": False, "bars": 0, "gaps": 0, "duplicates": 0}
    ts = [int(b["ts"]) for b in bars]
    duplicates = len(ts) - len(set(ts))
    gap_samples = [
        {"after": a, "before": b, "missing_minutes": max((b - a) // 60 - 1, 0)}
        for a, b in zip(ts, ts[1:])
        if b - a > 60
    ]
    gaps = len(gap_samples)
    backwards = sum(1 for a, b in zip(ts, ts[1:]) if b <= a)
    return {
        "ok": duplicates == 0 and backwards == 0 and gaps == 0,
        "bars": len(bars),
        "gaps": gaps,
        "duplicates": duplicates,
        "backwards": backwards,
        "gap_samples": gap_samples[:10],
        "start": datetime.fromtimestamp(ts[0], tz=timezone.utc).isoformat(),
        "end": datetime.fromtimestamp(ts[-1], tz=timezone.utc).isoformat(),
    }


def _baseline_trade_log(
    bars: list[dict[str, Any]],
    entries: list[int],
    exits: list[int],
    *,
    starting: float = STARTING,
) -> dict[str, Any]:
    slip = SLIPPAGE_BPS / 10_000.0
    cash = float(starting)
    equity_curve: list[dict[str, Any]] = [{"ts": bars[0]["ts"], "equity": cash}] if bars else []
    trades: list[dict[str, Any]] = []
    for entry_i, exit_i in zip(entries, exits):
        if exit_i <= entry_i or entry_i >= len(bars) or exit_i >= len(bars):
            continue
        entry_px = float(bars[entry_i]["close"]) * (1 + slip)
        exit_px = float(bars[exit_i]["close"]) * (1 - slip)
        notional = min(cash, starting)
        qty = notional / (entry_px * (1 + TAKER_FEE))
        entry_fee = entry_px * qty * TAKER_FEE
        exit_fee = exit_px * qty * TAKER_FEE
        pnl = (exit_px - entry_px) * qty - entry_fee - exit_fee
        window = bars[entry_i : exit_i + 1]
        lowest = min(float(b["low"]) for b in window)
        highest = max(float(b["high"]) for b in window)
        cash += pnl
        trades.append(
            {
                "entry_ts": bars[entry_i]["ts"],
                "exit_ts": bars[exit_i]["ts"],
                "entry_price": entry_px,
                "exit_price": exit_px,
                "pnl_usd": pnl,
                "mae_pct": (lowest / entry_px - 1) * 100,
                "mfe_pct": (highest / entry_px - 1) * 100,
            }
        )
        equity_curve.append({"ts": bars[exit_i]["ts"], "equity": cash})
    return {
        "summary": summarize_backtest(trades, equity_curve, starting),
        "trades": trades,
        "equity_curve": equity_curve,
    }


def buy_hold_benchmark(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if len(bars) < 2:
        return {"summary": summarize_backtest([], [], STARTING), "trades": []}
    return _baseline_trade_log(bars, [0], [len(bars) - 1])


def sma_baseline(
    bars: list[dict[str, Any]], short_len: int = 8, long_len: int = 21
) -> dict[str, Any]:
    bars5 = resample_bars(bars, 5, require_complete=True)
    closes = [float(b["close"]) for b in bars5]
    entries: list[int] = []
    exits: list[int] = []
    in_pos = False
    entry_i = 0
    for i in range(long_len + 1, len(bars5)):
        ps = sma(closes[:i], short_len)
        pl = sma(closes[:i], long_len)
        cs = sma(closes[: i + 1], short_len)
        cl = sma(closes[: i + 1], long_len)
        if None in (ps, pl, cs, cl):
            continue
        if not in_pos and ps <= pl and cs > cl:
            entry_i = i
            in_pos = True
        elif in_pos and ps >= pl and cs < cl:
            entries.append(entry_i)
            exits.append(i)
            in_pos = False
    if in_pos:
        entries.append(entry_i)
        exits.append(len(bars5) - 1)
    return _baseline_trade_log(bars5, entries, exits)


def donchian_baseline(
    bars: list[dict[str, Any]], entry_len: int = 20, exit_len: int = 10
) -> dict[str, Any]:
    bars5 = resample_bars(bars, 5, require_complete=True)
    entries: list[int] = []
    exits: list[int] = []
    in_pos = False
    entry_i = 0
    for i in range(max(entry_len, exit_len), len(bars5)):
        if not in_pos:
            high = max(float(x["high"]) for x in bars5[i - entry_len : i])
            if float(bars5[i]["close"]) > high:
                entry_i = i
                in_pos = True
        else:
            low = min(float(x["low"]) for x in bars5[i - exit_len : i])
            if float(bars5[i]["close"]) < low:
                entries.append(entry_i)
                exits.append(i)
                in_pos = False
    if in_pos:
        entries.append(entry_i)
        exits.append(len(bars5) - 1)
    return _baseline_trade_log(bars5, entries, exits)


def ema(values: list[float], length: int) -> list[float]:
    if not values or length <= 0:
        return []
    alpha = 2 / (length + 1)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1 - alpha) * out[-1])
    return out


def ema_baseline(
    bars: list[dict[str, Any]], fast_len: int = 12, slow_len: int = 26
) -> dict[str, Any]:
    bars5 = resample_bars(bars, 5, require_complete=True)
    closes = [float(b["close"]) for b in bars5]
    fast = ema(closes, fast_len)
    slow = ema(closes, slow_len)
    entries: list[int] = []
    exits: list[int] = []
    in_pos = False
    entry_i = 0
    for i in range(slow_len + 1, len(bars5)):
        if not in_pos and fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
            entry_i = i
            in_pos = True
        elif in_pos and fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
            entries.append(entry_i)
            exits.append(i)
            in_pos = False
    if in_pos:
        entries.append(entry_i)
        exits.append(len(bars5) - 1)
    return _baseline_trade_log(bars5, entries, exits)


def walk_forward_v3(
    bars: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    folds: int = 4,
) -> dict[str, Any]:
    config = dict(config or CHAMPION)
    n = len(bars)
    if n < 4_320:
        return {
            "ok": False,
            "reason": "need_at_least_3_days_of_1m_bars",
            "bars": n,
            "folds": [],
        }

    warm = 1_440
    remaining = n - warm
    fold_count = max(1, int(folds))
    results: list[dict[str, Any]] = []
    for fold_idx in range(fold_count):
        cursor = warm + (remaining * fold_idx) // fold_count
        end = warm + (remaining * (fold_idx + 1)) // fold_count
        if end <= cursor:
            continue
        segment = bars[max(0, cursor - warm) : end]
        result = replay(
            segment,
            config,
            detailed=True,
            start_index=warm,
        )
        results.append(
            {
                "oos_start": bars[cursor]["ts"],
                "oos_end": bars[end - 1]["ts"],
                "summary": result["summary"],
            }
        )

    profitable = sum(
        1 for x in results if float(x["summary"]["net_pnl_usd"]) > 0
    )
    return {
        "ok": True,
        "config": config,
        "folds": results,
        "profitable_folds": profitable,
        "total_folds": len(results),
        "positive_fold_ratio": (
            round(profitable / len(results), 6) if results else 0.0
        ),
    }


def _fold_aggregate(walk: dict[str, Any]) -> dict[str, Any]:
    folds = list(walk.get("folds") or [])
    summaries = [f.get("summary") or {} for f in folds]
    trades = sum(int(s.get("trades") or 0) for s in summaries)
    net = sum(float(s.get("net_pnl_usd") or 0) for s in summaries)
    gross_profit = sum(float(s.get("gross_profit_usd") or 0) for s in summaries)
    gross_loss = sum(float(s.get("gross_loss_usd") or 0) for s in summaries)
    return {
        "trades": trades,
        "net_pnl_usd": round(net, 4),
        "expectancy_usd": round(net / trades, 4) if trades else 0.0,
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "profit_factor": (
            round(gross_profit / gross_loss, 6)
            if gross_loss > 1e-12
            else None
        ),
        "max_fold_drawdown_pct": round(
            max((float(s.get("max_drawdown_pct") or 0) for s in summaries), default=0.0),
            6,
        ),
        "profitable_folds": int(walk.get("profitable_folds") or 0),
        "total_folds": int(walk.get("total_folds") or 0),
    }


def candidate_diagnostics(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, config in RESEARCH_CANDIDATES:
        full = replay(bars, dict(config), detailed=True)
        walk = walk_forward_v3(bars, dict(config))
        trade_log = list(full.get("trade_log") or [])
        reasons: dict[str, int] = {}
        for trade in trade_log:
            reason = str(trade.get("exit_reason") or "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        rows.append(
            {
                "name": name,
                "params": dict(config),
                "full_sample": full["summary"],
                "oos": _fold_aggregate(walk),
                "exit_reasons": reasons,
            }
        )
    return rows


def compare_strategies(bars: list[dict[str, Any]]) -> dict[str, Any]:
    v3 = replay(bars, dict(CHAMPION), detailed=True)
    quality = validate_bars(bars)
    return {
        "data_quality": quality,
        "valid_for_profitability_gate": bool(quality.get("ok")),
        "assumptions": {
            "taker_fee_rate": TAKER_FEE,
            "slippage_bps_each_side": SLIPPAGE_BPS,
            "live_trading": False,
        },
        "strategies": {
            "sma_trend_breakout_v3": v3["summary"],
            "buy_and_hold": buy_hold_benchmark(bars)["summary"],
            "sma_8_21": sma_baseline(bars)["summary"],
            "ema_12_26": ema_baseline(bars)["summary"],
            "donchian_20_10": donchian_baseline(bars)["summary"],
        },
        "walk_forward_v3": walk_forward_v3(bars),
        "candidate_diagnostics": candidate_diagnostics(bars),
    }


async def build_research_report(
    *,
    days: int = 30,
    symbol: str = "BTCUSD",
) -> dict[str, Any]:
    bars = await fetch_binance_history(symbol=symbol, days=days, interval="1m")
    report = compare_strategies(bars)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["source"] = "Binance.US public /api/v3/klines"
    report["symbol"] = symbol
    report["requested_days"] = days
    return report


def save_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
