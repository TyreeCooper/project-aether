"""Strict train/held-out split and validation gates for offline paper research."""
from __future__ import annotations

from typing import Any, Callable

from app.learn import CHAMPION, replay
from app.research import validate_bars


def held_out_validation(
    bars: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    *,
    train_fraction: float = 0.60,
    runner: Callable[..., dict[str, Any]] = replay,
) -> dict[str, Any]:
    """Evaluate once on a chronological holdout never passed to the train runner."""
    quality = validate_bars(bars)
    if not quality.get("ok"):
        return {"ok": False, "reason": "invalid_bar_history", "data_quality": quality}
    if len(bars) < 1_800:
        return {"ok": False, "reason": "insufficient_history", "bars": len(bars)}

    fraction = min(max(float(train_fraction), 0.50), 0.80)
    split = int(len(bars) * fraction)
    train = bars[:split]
    holdout = bars[split:]
    params = dict(config or CHAMPION)

    # Training result is diagnostic only; params are frozen before holdout runs.
    train_result = runner(train, dict(params), detailed=True)
    holdout_result = runner(holdout, dict(params), detailed=True)
    summary = dict(holdout_result.get("summary") or {})
    expectancy = float(summary.get("expectancy_usd") or 0.0)
    profit_factor = summary.get("profit_factor")
    gate_pass = expectancy >= 0 and profit_factor is not None and float(profit_factor) > 1.0

    return {
        "ok": True,
        "config": params,
        "split_index": split,
        "train": {"start": train[0]["ts"], "end": train[-1]["ts"], "bars": len(train),
                  "summary": train_result.get("summary")},
        "holdout": {"start": holdout[0]["ts"], "end": holdout[-1]["ts"], "bars": len(holdout),
                    "summary": summary},
        "profitability_gate_pass": gate_pass,
        "live_trading": False,
    }
