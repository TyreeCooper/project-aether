"""Canonical backend telemetry for AETHER's 17-gate PAPER flow.

The snapshot reports only observed runtime evidence. Counts that cannot be
independently observed are left as None; cumulative downstream evidence may prove
that a transition was passed without inventing an intermediate queue.
"""
from __future__ import annotations

from typing import Mapping, Sequence


CANONICAL_GATES = (
    (1, "CATALOG", "Discovery Admission"),
    (2, "FOCUS_ADMITTED", "Commissioning"),
    (3, "PRODUCT_BOUND", "Work Scheduler"),
    (4, "ROAMING_SCAN", "Executable Ingress"),
    (5, "MARKET_READY", "History & Warm-Up"),
    (6, "HISTORY_READY", "Closed-Bar Evaluation"),
    (7, "STRATEGY_EVALUATED", "Scout Admission"),
    (8, "WATCH", "Sniper Fire"),
    (9, "FIRE", "Risk / Size"),
    (10, "SIZE", "Clerk"),
    (11, "READY", "Portfolio Reserve"),
    (12, "RESERVED", "Paper Submit"),
    (13, "SUBMITTED", "Fill Guard"),
    (14, "OPEN", "Exit Management"),
    (15, "EXIT_REQUESTED", "Close Reservation"),
    (16, "CLOSE_RESERVED", "Paper Close Submit"),
    (17, "CLOSE_SUBMITTED", "Close Fill"),
)


def _count(rows: Mapping[str, Mapping[str, object]], *stages: str) -> int:
    wanted = set(stages)
    return sum(
        1
        for row in rows.values()
        if isinstance(row, Mapping) and str(row.get("stage") or "") in wanted
    )


def _gate(
    number: int,
    stage: str,
    label: str,
    *,
    input_count: int | None,
    pass_count: int | None,
    hold_count: int | None = 0,
    fault_count: int | None = 0,
    observability: str = "FULL",
) -> dict[str, object]:
    return {
        "number": number,
        "stage": stage,
        "label": label,
        "input": input_count,
        "pass": pass_count,
        "hold": hold_count,
        "fault": fault_count,
        "observability": observability,
    }


def build_canonical_gate_snapshot(
    *,
    pipeline: Mapping[str, object],
    dynamic_results: Mapping[str, Mapping[str, object]],
    exit_results: Mapping[str, Mapping[str, object]],
    registry_status: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    """Build Gate 01-17 telemetry from observed current-cycle state."""
    registry = registry_status or {}

    def observed_int(name: str) -> int | None:
        value = pipeline.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    received = registry.get("received")
    persisted = registry.get("persisted")
    received = None if isinstance(received, bool) or not isinstance(received, (int, float)) else int(received)
    persisted = None if isinstance(persisted, bool) or not isinstance(persisted, (int, float)) else int(persisted)

    focus = observed_int("focus_admitted")
    available = observed_int("dynamic_kraken_available")
    roaming = observed_int("roaming_batch")
    market_ready = observed_int("market_ready")
    history_ready = observed_int("history_ready")
    evaluated = observed_int("strategy_evaluated")
    market_wait = observed_int("market_not_ready")
    history_wait = observed_int("history_not_ready")
    eval_fault = observed_int("evaluation_error")

    stage = {
        name: _count(dynamic_results, name)
        for name in (
            "WATCH", "FIRE", "SIZE", "READY", "RESERVED",
            "SUBMITTED", "OPEN", "NO_SETUP", "REJECTED",
        )
    }
    entry_order = ("WATCH", "FIRE", "SIZE", "READY", "RESERVED", "SUBMITTED", "OPEN")

    def at_or_beyond(name: str) -> int:
        start = entry_order.index(name)
        return sum(stage[item] for item in entry_order[start:])

    exit_open = _count(exit_results, "OPEN")
    close_submitted = _count(exit_results, "CLOSE_SUBMITTED")
    flat = _count(exit_results, "FLAT")
    close_progress = close_submitted + flat

    scheduler_wait = (
        None
        if available is None or roaming is None
        else max(0, available - roaming)
    )

    gates = (
        _gate(1, "CATALOG", "Discovery Admission",
              input_count=received, pass_count=focus,
              hold_count=None, observability="PARTIAL" if received is None else "FULL"),
        _gate(2, "FOCUS_ADMITTED", "Commissioning",
              input_count=focus, pass_count=persisted,
              hold_count=None if focus is None or persisted is None else max(0, focus - persisted)),
        _gate(3, "PRODUCT_BOUND", "Work Scheduler",
              input_count=available, pass_count=roaming, hold_count=scheduler_wait),
        _gate(4, "ROAMING_SCAN", "Executable Ingress",
              input_count=roaming, pass_count=market_ready, hold_count=market_wait),
        _gate(5, "MARKET_READY", "History & Warm-Up",
              input_count=market_ready, pass_count=history_ready, hold_count=history_wait),
        _gate(6, "HISTORY_READY", "Closed-Bar Evaluation",
              input_count=history_ready, pass_count=evaluated, hold_count=0, fault_count=eval_fault),
        _gate(7, "STRATEGY_EVALUATED", "Scout Admission",
              input_count=evaluated, pass_count=at_or_beyond("WATCH"),
              hold_count=stage["NO_SETUP"]),
        _gate(8, "WATCH", "Sniper Fire",
              input_count=at_or_beyond("WATCH"), pass_count=at_or_beyond("FIRE"),
              hold_count=stage["WATCH"]),
        _gate(9, "FIRE", "Risk / Size",
              input_count=at_or_beyond("FIRE"), pass_count=at_or_beyond("SIZE"),
              hold_count=stage["FIRE"]),
        _gate(10, "SIZE", "Clerk",
              input_count=at_or_beyond("SIZE"), pass_count=at_or_beyond("READY"),
              hold_count=stage["SIZE"]),
        _gate(11, "READY", "Portfolio Reserve",
              input_count=at_or_beyond("READY"), pass_count=at_or_beyond("RESERVED"),
              hold_count=stage["READY"]),
        _gate(12, "RESERVED", "Paper Submit",
              input_count=at_or_beyond("RESERVED"), pass_count=at_or_beyond("SUBMITTED"),
              hold_count=stage["RESERVED"]),
        _gate(13, "SUBMITTED", "Fill Guard",
              input_count=at_or_beyond("SUBMITTED"), pass_count=stage["OPEN"],
              hold_count=stage["SUBMITTED"]),
        _gate(14, "OPEN", "Exit Management",
              input_count=exit_open + close_progress, pass_count=close_progress,
              hold_count=exit_open),
        _gate(15, "EXIT_REQUESTED", "Close Reservation",
              input_count=close_progress, pass_count=close_progress,
              hold_count=0, observability="CUMULATIVE"),
        _gate(16, "CLOSE_RESERVED", "Paper Close Submit",
              input_count=close_progress, pass_count=close_progress,
              hold_count=0, observability="CUMULATIVE"),
        _gate(17, "CLOSE_SUBMITTED", "Close Fill",
              input_count=close_progress, pass_count=flat,
              hold_count=close_submitted),
    )
    if tuple(row["number"] for row in gates) != tuple(range(1, 18)):
        raise RuntimeError("canonical gate telemetry must contain gates 1 through 17")
    return gates
