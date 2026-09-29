"""Per-asset intelligence source registry for AETHER vNext.

Trust controls evidence handling only. It never grants order authority.
Operator approval is required to transition a source into the trusted state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


TRUST_STATES = frozenset(
    {"candidate", "trusted", "untrusted", "disabled"}
)


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class AssetSourceRecord:
    source_id: str
    asset_id: str
    source_type: str
    platform: str
    name: str
    url: str
    tier: str
    trust_state: str
    origin: str
    ingestion_mode: str
    trade_influence_enabled: bool = False
    operator_approved_by: str | None = None
    operator_approved_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "asset_id",
            "source_type",
            "platform",
            "name",
            "url",
            "tier",
            "origin",
            "ingestion_mode",
        ):
            _canonical_text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.trust_state not in TRUST_STATES:
            raise ValueError("invalid trust_state")
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "source trust cannot enable trade influence"
            )
        if self.operator_approved_by is not None:
            _canonical_text(
                "operator_approved_by",
                self.operator_approved_by,
            )
        if (
            self.operator_approved_at_utc is not None
            and self.operator_approved_at_utc.tzinfo is None
        ):
            raise ValueError(
                "operator_approved_at_utc must be timezone-aware"
            )
        if self.trust_state == "trusted" and (
            self.operator_approved_by is None
            or self.operator_approved_at_utc is None
        ):
            raise ValueError(
                "trusted source requires explicit operator approval"
            )


@dataclass(frozen=True, slots=True)
class SourceTrustDecision:
    source_id: str
    prior_state: str
    new_state: str
    operator_id: str
    decided_at_utc: datetime
    rationale: str

    def __post_init__(self) -> None:
        for name in ("source_id", "operator_id", "rationale"):
            _canonical_text(name, getattr(self, name))
        if self.prior_state not in TRUST_STATES:
            raise ValueError("invalid prior_state")
        if self.new_state not in TRUST_STATES:
            raise ValueError("invalid new_state")
        if self.decided_at_utc.tzinfo is None:
            raise ValueError("decided_at_utc must be timezone-aware")


def apply_trust_decision(
    source: AssetSourceRecord,
    decision: SourceTrustDecision,
) -> AssetSourceRecord:
    if source.source_id != decision.source_id:
        raise ValueError("trust decision source_id mismatch")
    if source.trust_state != decision.prior_state:
        raise ValueError("trust decision prior_state mismatch")
    return replace(
        source,
        trust_state=decision.new_state,
        trade_influence_enabled=False,
        operator_approved_by=(
            decision.operator_id
            if decision.new_state == "trusted"
            else source.operator_approved_by
        ),
        operator_approved_at_utc=(
            decision.decided_at_utc
            if decision.new_state == "trusted"
            else source.operator_approved_at_utc
        ),
    )


def summarize_source_registry(
    sources: tuple[AssetSourceRecord, ...],
) -> dict[str, object]:
    if not isinstance(sources, tuple):
        raise ValueError("sources must be an immutable tuple")
    counts = {state: 0 for state in sorted(TRUST_STATES)}
    assets: set[str] = set()
    for source in sources:
        counts[source.trust_state] += 1
        assets.add(source.asset_id)
    return {
        "sources": len(sources),
        "assets": len(assets),
        "trust_states": counts,
        "trade_influence_enabled": False,
    }
