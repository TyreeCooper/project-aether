"""Bind deployed Phase-17 evidence to the fail-closed Full Swap readiness gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.full_swap_readiness import (
    FullSwapReadinessAssessment,
    FullSwapReadinessInput,
    assess_full_swap_readiness,
)
from aether_vnext.full_swap_runtime_evidence import (
    Phase17RuntimeEvidenceAssessment,
)


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class BookReconciliationEvidence:
    evidence_id: str
    deployed_revision: str
    observed_at_utc: datetime
    risk_admission_issues: tuple[str, ...]
    stale_order_intent_ids: tuple[str, ...]
    active_position_trade_identity_consistent: bool
    broker_ledger_balanced: bool
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in ("evidence_id", "deployed_revision"):
            _canonical_text(name, getattr(self, name))
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if not self.source_artifact_ids:
            raise ValueError("source_artifact_ids must not be empty")
        for source_id in self.source_artifact_ids:
            _canonical_text("source_artifact_id", source_id)
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("source_artifact_ids cannot contain duplicates")
        if self.synthetic is not False:
            raise ValueError("synthetic book reconciliation evidence is not admissible")

    @property
    def verified(self) -> bool:
        return bool(
            not self.risk_admission_issues
            and not self.stale_order_intent_ids
            and self.active_position_trade_identity_consistent
            and self.broker_ledger_balanced
            and not self.synthetic
        )


@dataclass(frozen=True, slots=True)
class FullSwapEvidenceBoundInput:
    assessment_id: str
    assessed_at_utc: datetime
    runtime_evidence: Phase17RuntimeEvidenceAssessment
    book_reconciliation: BookReconciliationEvidence
    phase16_internal_closeout_green: bool
    vnext_ci_green: bool
    repository_ci_green: bool
    legacy_runtime_authority_retirable: bool
    paper_only: bool
    live_blocked: bool

    def __post_init__(self) -> None:
        _canonical_text("assessment_id", self.assessment_id)
        if self.assessed_at_utc.tzinfo is None:
            raise ValueError("assessed_at_utc must be timezone-aware")
        if (
            self.runtime_evidence.deployed_revision
            != self.book_reconciliation.deployed_revision
        ):
            raise ValueError(
                "runtime evidence and book reconciliation must share one deployed revision"
            )


def assess_evidence_bound_full_swap_readiness(
    value: FullSwapEvidenceBoundInput,
) -> FullSwapReadinessAssessment:
    """Derive runtime-sensitive readiness checks from admitted evidence objects."""
    return assess_full_swap_readiness(
        FullSwapReadinessInput(
            assessment_id=value.assessment_id,
            assessed_at_utc=value.assessed_at_utc,
            phase16_internal_closeout_green=(
                value.phase16_internal_closeout_green
            ),
            phase16_runtime_shadow_verified=(
                value.runtime_evidence.runtime_shadow_verified
            ),
            vnext_ci_green=value.vnext_ci_green,
            repository_ci_green=value.repository_ci_green,
            canonical_vnext_book_reconciled=value.book_reconciliation.verified,
            restart_recovery_verified=(
                value.runtime_evidence.restart_recovery_verified
            ),
            rollback_path_verified=value.runtime_evidence.rollback_verified,
            legacy_runtime_authority_retirable=(
                value.legacy_runtime_authority_retirable
            ),
            paper_only=value.paper_only,
            live_blocked=value.live_blocked,
        )
    )
