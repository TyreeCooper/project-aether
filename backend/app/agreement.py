"""Agreement gate between held-out validation and forward real-paper evidence.

Agreement can identify a champion candidate. It never enables live trading.
"""
from __future__ import annotations

from typing import Any


def strategy_agreement(
    held_out: dict[str, Any],
    forward: dict[str, Any],
) -> dict[str, Any]:
    """Require independent profitability gates and a meaningful forward sample."""
    held_ok = bool(
        held_out.get("ok")
        and held_out.get("profitability_gate_pass")
    )
    forward_profitability = bool(
        forward.get("ok")
        and forward.get("profitability_gate_pass")
    )
    sample_defined = bool(forward.get("sample_gate_defined"))
    sample_pass = bool(forward.get("sample_gate_pass"))
    forward_ok = bool(
        forward.get("forward_gate_pass")
        and forward_profitability
        and sample_defined
        and sample_pass
    )
    agree = held_ok and forward_ok

    config = held_out.get("config")
    champion_candidate = dict(config) if agree and isinstance(config, dict) else None
    blockers: list[str] = []
    if not held_ok:
        blockers.append("held_out_profitability_gate")
    if not forward_profitability:
        blockers.append("forward_profitability_gate")
    if not sample_defined:
        blockers.append("forward_meaningful_sample_threshold")
    elif not sample_pass:
        blockers.append("forward_meaningful_sample")

    return {
        "ok": True,
        "agreement": agree,
        "champion_candidate": champion_candidate,
        "held_out_gate_pass": held_ok,
        "forward_gate_pass": forward_ok,
        "blockers": blockers,
        "live_trading": False,
        "note": (
            "Champion candidate requires held-out expectancy >= 0 with profit factor > 1 "
            "and forward real-paper expectancy >= 0 with profit factor > 1 plus an "
            "explicitly defined meaningful sample. Live execution remains blocked."
        ),
    }
