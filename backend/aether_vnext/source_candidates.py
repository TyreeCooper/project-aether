"""Secure intelligence source-candidate staging for AETHER vNext.

Discovery and trust are deliberately separate. This module accepts candidate
metadata from any future discovery adapter, but can only emit a candidate
AssetSourceRecord. Operator trust decisions remain a separate audited path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.source_registry import AssetSourceRecord


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    candidate_id: str
    asset_id: str
    source_type: str
    platform: str
    name: str
    url: str
    tier: str
    discovery_origin: str
    ingestion_mode: str
    discovered_at_utc: datetime
    evidence_ref: str
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "asset_id",
            "source_type",
            "platform",
            "name",
            "url",
            "tier",
            "discovery_origin",
            "ingestion_mode",
            "evidence_ref",
        ):
            _canonical_text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.discovered_at_utc.tzinfo is None:
            raise ValueError("discovered_at_utc must be timezone-aware")
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "source candidate cannot enable trade influence"
            )


@dataclass(frozen=True, slots=True)
class CandidateReview:
    candidate_id: str
    reviewed_by: str
    reviewed_at_utc: datetime
    accepted_for_registry: bool
    rationale: str

    def __post_init__(self) -> None:
        for name in ("candidate_id", "reviewed_by", "rationale"):
            _canonical_text(name, getattr(self, name))
        if self.reviewed_at_utc.tzinfo is None:
            raise ValueError("reviewed_at_utc must be timezone-aware")
        if not isinstance(self.accepted_for_registry, bool):
            raise ValueError("accepted_for_registry must be boolean")


def stage_candidate_as_source(
    candidate: SourceCandidate,
    review: CandidateReview,
) -> AssetSourceRecord:
    if candidate.candidate_id != review.candidate_id:
        raise ValueError("candidate review identity mismatch")
    if not review.accepted_for_registry:
        raise ValueError("candidate requires operator acceptance")
    return AssetSourceRecord(
        source_id=candidate.candidate_id,
        asset_id=candidate.asset_id,
        source_type=candidate.source_type,
        platform=candidate.platform,
        name=candidate.name,
        url=candidate.url,
        tier=candidate.tier,
        trust_state="candidate",
        origin=candidate.discovery_origin,
        ingestion_mode=candidate.ingestion_mode,
        trade_influence_enabled=False,
        operator_approved_by=None,
        operator_approved_at_utc=None,
    )
