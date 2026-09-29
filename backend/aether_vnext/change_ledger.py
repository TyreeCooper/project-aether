"""Canonical C9.5 document/change-ledger contract for AETHER vNext.

Every material specification/version/change carries an immutable identity,
canonical UTC timestamp, source/configuration lineage, and explicit evidence-reset
semantics. This module describes records only; it grants no trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ChangeLedgerEntry:
    change_id: str
    version: str
    timestamp: datetime
    section_changed: str
    reason: str
    logic_changed: bool
    evidence_n_reset: bool
    superseded_version_reference: str | None
    source_ref: str
    configuration_hash: str

    def __post_init__(self) -> None:
        for name in (
            "change_id",
            "version",
            "section_changed",
            "reason",
            "source_ref",
            "configuration_hash",
        ):
            _canonical_text(name, getattr(self, name))
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if not isinstance(self.logic_changed, bool):
            raise ValueError("logic_changed must be boolean")
        if not isinstance(self.evidence_n_reset, bool):
            raise ValueError("evidence_n_reset must be boolean")
        if self.superseded_version_reference is not None:
            _canonical_text(
                "superseded_version_reference",
                self.superseded_version_reference,
            )

    @property
    def timestamp_utc(self) -> datetime:
        return self.timestamp.astimezone(timezone.utc)


def build_change_ledger(
    entries: Iterable[ChangeLedgerEntry],
) -> tuple[dict[str, object], ...]:
    """Return deterministic append-only ledger records with canonical UTC time."""
    rows = tuple(entries)
    ids = tuple(row.change_id for row in rows)
    if len(ids) != len(set(ids)):
        raise ValueError("change_id must be unique within change ledger")

    ordered = sorted(
        rows,
        key=lambda row: (row.timestamp_utc, row.change_id),
    )
    return tuple(
        {
            "change_id": row.change_id,
            "version": row.version,
            "timestamp": row.timestamp_utc.isoformat(),
            "section_changed": row.section_changed,
            "reason": row.reason,
            "logic_changed": row.logic_changed,
            "evidence_n_reset": row.evidence_n_reset,
            "superseded_version_reference": row.superseded_version_reference,
            "source_ref": row.source_ref,
            "configuration_hash": row.configuration_hash,
            "authority": {
                "read_only": True,
                "execution_permission": False,
                "may_award_independent_evidence_credit": False,
            },
        }
        for row in ordered
    )
