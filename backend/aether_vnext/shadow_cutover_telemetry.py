"""Read-only shadow-cutover diagnostics for AETHER vNext Phase 16.

Canonical diagnostics are descriptive only:
Universe -> WATCH -> FIRE -> SIZE -> READY -> ORDER -> OPEN,
first-killer distribution, dwell time, and explicit prior-policy counterfactuals.
Shadow comparison never creates an order and never grants trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Any


FUNNEL_STAGES = (
    "UNIVERSE",
    "WATCH",
    "FIRE",
    "SIZE",
    "READY",
    "ORDER",
    "OPEN",
)

_STAGE_BY_SEAT = {
    "Scout": "WATCH",
    "Sniper": "FIRE",
    "Risk": "SIZE",
    "Clerk": "READY",
    "Portfolio": "ORDER",
    "Floor": "OPEN",
}


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PriorPolicyShadowObservation:
    observation_id: str
    candidate_ref: str
    route_id: str
    prior_policy_version: str
    current_policy_version: str
    observed_at_utc: datetime
    would_have_passed_prior_policy: bool | None
    prior_policy_blocker: str | None = None
    order_created: bool = False
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "candidate_ref",
            "route_id",
            "prior_policy_version",
            "current_policy_version",
        ):
            _canonical_text(name, getattr(self, name))
        _aware("observed_at_utc", self.observed_at_utc)
        if self.prior_policy_blocker is not None:
            _canonical_text("prior_policy_blocker", self.prior_policy_blocker)
        if self.would_have_passed_prior_policy is True and self.prior_policy_blocker is not None:
            raise ValueError("passing prior-policy comparison cannot carry a blocker")
        if self.would_have_passed_prior_policy is False and self.prior_policy_blocker is None:
            raise ValueError("blocked prior-policy comparison requires blocker")
        if self.order_created is not False:
            raise ValueError("shadow comparison cannot create an order")
        if self.trade_influence_enabled is not False:
            raise ValueError("shadow comparison cannot influence trading")


def _event_stage(row: Mapping[str, Any]) -> str | None:
    seat = row.get("seat")
    if seat is None:
        return None
    return _STAGE_BY_SEAT.get(str(seat))


def _event_time(row: Mapping[str, Any]) -> datetime:
    value = row.get("created_at_utc")
    if not isinstance(value, datetime):
        raise ValueError("event created_at_utc must be datetime")
    return _aware("event created_at_utc", value)


def _funnel_counts(
    *,
    universe_count: int,
    events: tuple[Mapping[str, Any], ...],
) -> dict[str, int]:
    if (
        not isinstance(universe_count, int)
        or isinstance(universe_count, bool)
        or universe_count < 0
    ):
        raise ValueError("universe_count must be a nonnegative integer")

    reached: dict[str, set[str]] = {stage: set() for stage in FUNNEL_STAGES[1:]}
    for row in events:
        stage = _event_stage(row)
        if stage is None:
            continue
        aggregate_id = _canonical_text("aggregate_id", row.get("aggregate_id"))
        reached[stage].add(aggregate_id)

    return {
        "UNIVERSE": universe_count,
        **{stage: len(reached[stage]) for stage in FUNNEL_STAGES[1:]},
    }


def _first_killer_distribution(
    lineages: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, object], ...]:
    counts: dict[tuple[str, str], int] = {}
    for row in lineages:
        killer = row.get("first_killed_by")
        reason = row.get("first_kill_reason")
        if killer is None and reason is None:
            continue
        if killer is None or reason is None:
            raise ValueError("first-killer lineage requires both seat and reason")
        key = (
            _canonical_text("first_killed_by", killer),
            _canonical_text("first_kill_reason", reason),
        )
        counts[key] = counts.get(key, 0) + 1

    return tuple(
        {
            "seat": seat,
            "reason": reason,
            "count": count,
        }
        for (seat, reason), count in sorted(counts.items())
    )


def _dwell_rows(
    events: tuple[Mapping[str, Any], ...],
    *,
    as_of_utc: datetime,
) -> tuple[dict[str, object], ...]:
    _aware("as_of_utc", as_of_utc)
    grouped: dict[str, list[tuple[datetime, str]]] = {}
    for row in events:
        stage = _event_stage(row)
        if stage is None:
            continue
        aggregate_id = _canonical_text("aggregate_id", row.get("aggregate_id"))
        timestamp = _event_time(row)
        if timestamp > as_of_utc:
            continue
        grouped.setdefault(aggregate_id, []).append((timestamp, stage))

    output: list[dict[str, object]] = []
    for aggregate_id, transitions in sorted(grouped.items()):
        transitions.sort(key=lambda item: (item[0], FUNNEL_STAGES.index(item[1])))
        for index, (entered_at, stage) in enumerate(transitions):
            exited_at = (
                transitions[index + 1][0]
                if index + 1 < len(transitions)
                else as_of_utc
            )
            duration_s = (exited_at - entered_at).total_seconds()
            if duration_s < 0:
                raise ValueError("shadow dwell time cannot be negative")
            output.append(
                {
                    "aggregate_id": aggregate_id,
                    "stage": stage,
                    "entered_at_utc": entered_at.isoformat(),
                    "exited_at_utc": exited_at.isoformat(),
                    "dwell_seconds": duration_s,
                }
            )
    return tuple(output)


def build_shadow_cutover_telemetry(
    *,
    as_of_utc: datetime,
    universe_count: int,
    event_rows: Iterable[Mapping[str, Any]],
    decision_lineage_rows: Iterable[Mapping[str, Any]],
    prior_policy_observations: Iterable[PriorPolicyShadowObservation] = (),
) -> dict[str, object]:
    """Build descriptive shadow telemetry without cutover or execution authority."""
    _aware("as_of_utc", as_of_utc)
    events = tuple(event_rows)
    lineages = tuple(decision_lineage_rows)
    comparisons = tuple(prior_policy_observations)

    for row in events:
        event_time = _event_time(row)
        if event_time > as_of_utc:
            raise ValueError("future event cannot enter shadow telemetry")
    for observation in comparisons:
        if observation.observed_at_utc > as_of_utc:
            raise ValueError("future prior-policy observation cannot enter shadow telemetry")

    passed = sum(
        row.would_have_passed_prior_policy is True for row in comparisons
    )
    blocked = sum(
        row.would_have_passed_prior_policy is False for row in comparisons
    )
    unknown = len(comparisons) - passed - blocked

    return {
        "as_of_utc": as_of_utc.isoformat(),
        "mode": "shadow",
        "authority": {
            "read_only": True,
            "execution_permission": False,
            "may_create_orders": False,
            "may_mutate_firm_state": False,
            "may_enable_live": False,
            "comparison_is_diagnostic_only": True,
        },
        "traffic_funnel": _funnel_counts(
            universe_count=universe_count,
            events=events,
        ),
        "first_killer_distribution": list(
            _first_killer_distribution(lineages)
        ),
        "dwell_time": list(_dwell_rows(events, as_of_utc=as_of_utc)),
        "prior_policy_shadow": {
            "observation_count": len(comparisons),
            "would_have_passed": passed,
            "would_have_blocked": blocked,
            "unknown": unknown,
            "records": [
                {
                    "observation_id": row.observation_id,
                    "candidate_ref": row.candidate_ref,
                    "route_id": row.route_id,
                    "prior_policy_version": row.prior_policy_version,
                    "current_policy_version": row.current_policy_version,
                    "observed_at_utc": row.observed_at_utc.isoformat(),
                    "would_have_passed_prior_policy": (
                        row.would_have_passed_prior_policy
                    ),
                    "prior_policy_blocker": row.prior_policy_blocker,
                    "order_created": False,
                    "trade_influence_enabled": False,
                }
                for row in comparisons
            ],
        },
    }
