"""MF-03 failure-isolated Feed Mesh contracts.

Every source/transport lane owns bounded capacity, explicit overflow behavior,
circuit-breaker state, and loss telemetry. Witness or analytics pressure must never
globally stall executable market truth.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Generic, TypeVar


T = TypeVar("T")


class LanePriority(IntEnum):
    EXECUTABLE = 100
    WITNESS = 60
    DEPTH = 40
    ANALYTICS = 20


class OverflowAction(StrEnum):
    REJECT_NEW = "REJECT_NEW"
    SHED_OLDEST = "SHED_OLDEST"


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class LanePolicy:
    capacity: int
    high_water_mark: int
    priority: LanePriority
    overflow_action: OverflowAction
    failure_threshold: int = 3

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("capacity must be positive")
        if self.high_water_mark < 1 or self.high_water_mark > self.capacity:
            raise ValueError("high_water_mark must be within capacity")
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")


@dataclass(slots=True)
class LaneTelemetry:
    admitted: int = 0
    consumed: int = 0
    overflow_events: int = 0
    shed_events: int = 0
    rejected_events: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    recoveries: int = 0


@dataclass(slots=True)
class FeedLane(Generic[T]):
    lane_id: str
    policy: LanePolicy
    _queue: deque[T] = field(default_factory=deque)
    telemetry: LaneTelemetry = field(default_factory=LaneTelemetry)
    circuit_state: CircuitState = CircuitState.CLOSED

    def __post_init__(self) -> None:
        self.lane_id = str(self.lane_id).strip()
        if not self.lane_id:
            raise ValueError("lane_id is required")

    @property
    def depth(self) -> int:
        return len(self._queue)

    @property
    def pressure_high(self) -> bool:
        return self.depth >= self.policy.high_water_mark

    @property
    def fidelity_degraded(self) -> bool:
        return bool(self.telemetry.shed_events or self.telemetry.rejected_events)

    def enqueue(self, item: T) -> bool:
        if self.circuit_state is CircuitState.OPEN:
            self.telemetry.rejected_events += 1
            return False
        if self.depth >= self.policy.capacity:
            self.telemetry.overflow_events += 1
            if self.policy.overflow_action is OverflowAction.REJECT_NEW:
                self.telemetry.rejected_events += 1
                return False
            self._queue.popleft()
            self.telemetry.shed_events += 1
        self._queue.append(item)
        self.telemetry.admitted += 1
        return True

    def dequeue(self) -> T | None:
        if not self._queue:
            return None
        self.telemetry.consumed += 1
        return self._queue.popleft()

    def record_failure(self) -> None:
        self.telemetry.failures += 1
        self.telemetry.consecutive_failures += 1
        if self.telemetry.consecutive_failures >= self.policy.failure_threshold:
            self.circuit_state = CircuitState.OPEN

    def record_success(self) -> None:
        if self.circuit_state is CircuitState.OPEN:
            self.telemetry.recoveries += 1
        self.telemetry.consecutive_failures = 0
        self.circuit_state = CircuitState.CLOSED


@dataclass(slots=True)
class MarketFabricFeedMesh(Generic[T]):
    lanes: dict[str, FeedLane[T]] = field(default_factory=dict)

    def add_lane(self, lane: FeedLane[T]) -> None:
        if lane.lane_id in self.lanes:
            raise ValueError(f"duplicate lane_id: {lane.lane_id}")
        self.lanes[lane.lane_id] = lane

    def lane(self, lane_id: str) -> FeedLane[T]:
        return self.lanes[str(lane_id)]

    def enqueue(self, lane_id: str, item: T) -> bool:
        return self.lane(lane_id).enqueue(item)

    def snapshot(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "lane_id": lane.lane_id,
                "priority": lane.policy.priority.name,
                "capacity": lane.policy.capacity,
                "depth": lane.depth,
                "high_water_mark": lane.policy.high_water_mark,
                "pressure_high": lane.pressure_high,
                "circuit_state": lane.circuit_state.value,
                "fidelity_degraded": lane.fidelity_degraded,
                "overflow_events": lane.telemetry.overflow_events,
                "shed_events": lane.telemetry.shed_events,
                "rejected_events": lane.telemetry.rejected_events,
            }
            for lane in sorted(
                self.lanes.values(),
                key=lambda value: (-int(value.policy.priority), value.lane_id),
            )
        )
