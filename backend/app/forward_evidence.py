"""Forward paper-evidence gate for newly observed strategy exits.

This module scores real paper fills only. It never authorizes live execution.
"""
from __future__ import annotations

from typing import Any

from app.learn import STRATEGY_ACTOR_PREFIX, score_exits


def forward_paper_evidence(
    fills: list[dict[str, Any]],
    *,
    actor_prefix: str = STRATEGY_ACTOR_PREFIX,
    minimum_exits: int | None = None,
) -> dict[str, Any]:
    """Score the forward paper cohort and expose profitability/sample gates."""
    score = score_exits(fills, actor_prefix=actor_prefix)
    expectancy = float(score.get("expectancy_usd") or 0.0)
    profit_factor = score.get("profit_factor")
    profitability_gate = (
        expectancy >= 0
        and profit_factor is not None
        and float(profit_factor) > 1.0
    )
    sample_gate = (
        minimum_exits is not None
        and int(minimum_exits) > 0
        and int(score.get("closed") or 0) >= int(minimum_exits)
    )
    return {
        "ok": True,
        "evidence": score,
        "profitability_gate_pass": profitability_gate,
        "sample_gate_defined": minimum_exits is not None and int(minimum_exits) > 0,
        "sample_gate_pass": sample_gate,
        "forward_gate_pass": profitability_gate and sample_gate,
        "live_trading": False,
        "note": (
            "Forward real-paper evidence only. A meaningful sample threshold must "
            "be explicitly defined before this evidence can satisfy the forward gate."
        ),
    }
