"""Fail-closed readiness contract for AETHER Phase 17 Full Swap-Out.

Phase 17 retires legacy runtime authority only after the production-shaped shadow
path and recovery/reconciliation safety have been proved. This module is read-only:
it does not switch runtimes, deploy code, start a trading loop, or authorize live
execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FullSwapReadinessInput:
    assessment_id: str
    assessed_at_utc: datetime
    phase16_internal_closeout_green: bool
    phase16_runtime_shadow_verified: bool
    vnext_ci_green: bool
    repository_ci_green: bool
    canonical_vnext_book_reconciled: bool
    restart_recovery_verified: bool
    rollback_path_verified: bool
    legacy_runtime_authority_retirable: bool
    paper_only: bool
    live_blocked: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.assessment_id, str)
            or not self.assessment_id
            or self.assessment_id != self.assessment_id.strip()
        ):
            raise ValueError("assessment_id must be canonical text")
        if self.assessed_at_utc.tzinfo is None:
            raise ValueError("assessed_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FullSwapReadinessAssessment:
    assessment_id: str
    assessed_at_utc: datetime
    swap_ready: bool
    live_execution_authorized: bool
    blocking_reasons: tuple[str, ...]
    checks: tuple[tuple[str, bool], ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "assessed_at_utc": self.assessed_at_utc.isoformat(),
            "swap_ready": self.swap_ready,
            "live_execution_authorized": False,
            "blocking_reasons": list(self.blocking_reasons),
            "checks": {name: value for name, value in self.checks},
        }


def assess_full_swap_readiness(
    value: FullSwapReadinessInput,
) -> FullSwapReadinessAssessment:
    """Assess cutover readiness without mutating runtime authority."""
    checks = (
        ("phase16_internal_closeout_green", value.phase16_internal_closeout_green),
        ("phase16_runtime_shadow_verified", value.phase16_runtime_shadow_verified),
        ("vnext_ci_green", value.vnext_ci_green),
        ("repository_ci_green", value.repository_ci_green),
        ("canonical_vnext_book_reconciled", value.canonical_vnext_book_reconciled),
        ("restart_recovery_verified", value.restart_recovery_verified),
        ("rollback_path_verified", value.rollback_path_verified),
        (
            "legacy_runtime_authority_retirable",
            value.legacy_runtime_authority_retirable,
        ),
        ("paper_only", value.paper_only),
        ("live_blocked", value.live_blocked),
    )
    blockers = tuple(name for name, passed in checks if not passed)

    return FullSwapReadinessAssessment(
        assessment_id=value.assessment_id,
        assessed_at_utc=value.assessed_at_utc,
        swap_ready=not blockers,
        live_execution_authorized=False,
        blocking_reasons=blockers,
        checks=checks,
    )
