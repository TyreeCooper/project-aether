"""Structured audit events used by the operator console and future persistence."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEvent:
    ts_utc: str
    level: str
    actor: str
    component: str
    event: str
    correlation_id: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        level: str,
        message: str,
        actor: str = "system",
        component: str = "engine",
        event: str = "message",
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "AuditEvent":
        return cls(
            ts_utc=_utc_now(),
            level=level,
            actor=actor,
            component=component,
            event=event,
            correlation_id=correlation_id or f"evt-{uuid4().hex}",
            message=message,
            payload=payload or {},
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Temporary compatibility alias for the current frontend.
        data["ts"] = self.ts_utc
        return data


class InMemoryAuditSink:
    def __init__(self, max_events: int = 500) -> None:
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)

    def emit(self, event: AuditEvent) -> None:
        self.events.appendleft(event.to_dict())
