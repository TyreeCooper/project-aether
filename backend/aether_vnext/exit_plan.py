"""Typed ExitPlan frozen at OPEN."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ExitReason(StrEnum):
    GOVERNOR_HALT = "governor_halt"
    HARD_STOP = "hard_stop"
    STALE_MARK = "stale_mark"
    SESSION_FLATTEN = "session_flatten"
    STRUCTURE = "structure"
    TIME_STOP = "time_stop"
    TRAIL = "trail"
    PROFIT_TAKE = "profit_take"
    PLAN_COMPLETE = "plan_complete"


EXIT_PRECEDENCE: tuple[ExitReason, ...] = (
    ExitReason.GOVERNOR_HALT,
    ExitReason.HARD_STOP,
    ExitReason.STALE_MARK,
    ExitReason.SESSION_FLATTEN,
    ExitReason.STRUCTURE,
    ExitReason.TIME_STOP,
    ExitReason.TRAIL,
    ExitReason.PROFIT_TAKE,
)


@dataclass(frozen=True, slots=True)
class TrailingPolicy:
    enabled: bool
    start_condition: dict[str, Any] | None
    ratchet_rule: dict[str, Any] | None
    never_loosen: bool = True


@dataclass(frozen=True, slots=True)
class ProfitTakePolicy:
    enabled: bool
    rule_id: str | None


@dataclass(frozen=True, slots=True)
class ExitPlan:
    exit_plan_id: str
    version: str
    hard_stop_price: float | None
    structure_rule_id: str | None
    time_stop_deadline_utc: datetime | None
    trailing_policy: TrailingPolicy
    profit_take_policy: ProfitTakePolicy
    session_close_policy: str
    stale_mark_policy: str
    governor_halt_behavior: str
    created_from_playbook_version: str
