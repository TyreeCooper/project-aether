"""Versioned paper-trade journal with stable strategy attribution.

This module is persistence/replay plumbing only. It never authorizes execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable

JOURNAL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TradeJournalEntry:
    event_id: str
    ts: str
    event: str
    strategy_id: str
    strategy_version: str
    horizon: str
    payload: dict[str, Any]
    schema_version: int = JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != JOURNAL_SCHEMA_VERSION:
            raise ValueError("unsupported_journal_schema")
        for value, name in (
            (self.event_id, "event_id"),
            (self.ts, "ts"),
            (self.event, "event"),
            (self.strategy_id, "strategy_id"),
            (self.strategy_version, "strategy_version"),
            (self.horizon, "horizon"),
        ):
            if not str(value).strip():
                raise ValueError(f"journal_{name}_required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "TradeJournalEntry":
        version = int(row.get("schema_version", 0))
        if version != JOURNAL_SCHEMA_VERSION:
            raise ValueError("unsupported_journal_schema")
        return cls(
            event_id=str(row.get("event_id", "")),
            ts=str(row.get("ts", "")),
            event=str(row.get("event", "")),
            strategy_id=str(row.get("strategy_id", "")),
            strategy_version=str(row.get("strategy_version", "")),
            horizon=str(row.get("horizon", "")),
            payload=dict(row.get("payload") or {}),
            schema_version=version,
        )


def dump_journal(entries: Iterable[TradeJournalEntry]) -> str:
    """Serialize entries as deterministic JSON Lines for durable replay."""
    return "".join(
        json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        for entry in entries
    )


def load_journal(raw: str) -> list[TradeJournalEntry]:
    """Replay journal text without losing strategy/version/horizon attribution."""
    entries: list[TradeJournalEntry] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("journal_row_must_be_object")
        entries.append(TradeJournalEntry.from_dict(row))
    return entries
