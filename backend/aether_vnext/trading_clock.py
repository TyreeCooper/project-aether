"""AETHER vNext Trading Clock / Horizon Controller.

A route becomes due from an explicit playbook trigger interval and a completed bar.
The clock never invents a universal interval merely from the horizon label because
AETHER playbooks can use different trigger intervals inside the same horizon family.

Replay and paper call this same controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from aether_vnext.bars import Bar
from aether_vnext.calendars import CalendarDecision


@dataclass(frozen=True, slots=True)
class RouteClockSpec:
    route_key: str
    asset_id: str
    horizon: str
    trigger_interval: timedelta
    active: bool = True
    supported: bool = True

    def __post_init__(self) -> None:
        if not self.route_key:
            raise ValueError("route_key is required")
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if not self.horizon:
            raise ValueError("horizon is required")
        if self.trigger_interval.total_seconds() <= 0:
            raise ValueError("trigger_interval must be positive")


@dataclass(frozen=True, slots=True)
class ClockDecision:
    route_key: str
    due: bool
    reason: str
    bar_close_utc: datetime | None


class TradingClock:
    """Stateful one-evaluation-per-completed-trigger-bar controller."""

    def __init__(self) -> None:
        self._last_consumed_close: dict[str, datetime] = {}

    def inspect(
        self,
        *,
        spec: RouteClockSpec,
        closed_bar: Bar | None,
        calendar: CalendarDecision,
        as_of_utc: datetime,
    ) -> ClockDecision:
        if as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if not spec.supported:
            return ClockDecision(spec.route_key, False, "route_unsupported", None)
        if not spec.active:
            return ClockDecision(spec.route_key, False, "route_inactive", None)
        if not calendar.eligible:
            return ClockDecision(spec.route_key, False, "session_closed", None)
        if closed_bar is None:
            return ClockDecision(spec.route_key, False, "forming_bar", None)
        if closed_bar.asset_id != spec.asset_id:
            return ClockDecision(
                spec.route_key,
                False,
                "bar_asset_mismatch",
                closed_bar.bucket_close_utc,
            )
        if closed_bar.interval != spec.trigger_interval:
            return ClockDecision(
                spec.route_key,
                False,
                "wrong_trigger_interval",
                closed_bar.bucket_close_utc,
            )
        if closed_bar.bucket_close_utc > as_of_utc:
            return ClockDecision(
                spec.route_key,
                False,
                "forming_bar",
                closed_bar.bucket_close_utc,
            )

        prior = self._last_consumed_close.get(spec.route_key)
        if prior is not None and closed_bar.bucket_close_utc <= prior:
            return ClockDecision(
                spec.route_key,
                False,
                "clock_already_consumed",
                closed_bar.bucket_close_utc,
            )

        return ClockDecision(
            spec.route_key,
            True,
            "clock_due",
            closed_bar.bucket_close_utc,
        )

    def consume(self, decision: ClockDecision) -> None:
        if not decision.due or decision.bar_close_utc is None:
            raise ValueError("only a due clock decision can be consumed")
        prior = self._last_consumed_close.get(decision.route_key)
        if prior is not None and decision.bar_close_utc <= prior:
            raise ValueError("clock decision is stale or already consumed")
        self._last_consumed_close[decision.route_key] = decision.bar_close_utc

    def last_consumed_close(self, route_key: str) -> datetime | None:
        return self._last_consumed_close.get(route_key)
