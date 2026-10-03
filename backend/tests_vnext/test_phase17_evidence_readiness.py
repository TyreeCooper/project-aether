from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.full_swap_evidence_readiness import (
    BookReconciliationEvidence,
    FullSwapEvidenceBoundInput,
    assess_evidence_bound_full_swap_readiness,
)
from aether_vnext.full_swap_runtime_evidence import (
    Phase17RuntimeEvidenceAssessment,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 19, 0, tzinfo=UTC)
REV = "cafebabe" * 5


def _runtime(**overrides) -> Phase17RuntimeEvidenceAssessment:
    values = {
        "deployed_revision": REV,
        "runtime_shadow_verified": True,
        "restart_recovery_verified": True,
        "rollback_verified": True,
        "activation_evidence_complete": True,
        "blocking_reasons": (),
    }
    values.update(overrides)
    return Phase17RuntimeEvidenceAssessment(**values)


def _book(**overrides) -> BookReconciliationEvidence:
    values = {
        "evidence_id": "book-reconcile-1",
        "deployed_revision": REV,
        "observed_at_utc": T0,
        "risk_admission_issues": (),
        "stale_order_intent_ids": (),
        "active_position_trade_identity_consistent": True,
        "broker_ledger_balanced": True,
        "source_artifact_ids": ("book-health-run-1",),
        "synthetic": False,
    }
    values.update(overrides)
    return BookReconciliationEvidence(**values)


def _input(**overrides) -> FullSwapEvidenceBoundInput:
    values = {
        "assessment_id": "phase17-evidence-bound",
        "assessed_at_utc": T0,
        "runtime_evidence": _runtime(),
        "book_reconciliation": _book(),
        "phase16_internal_closeout_green": True,
        "vnext_ci_green": True,
        "repository_ci_green": True,
        "legacy_runtime_authority_retirable": True,
        "paper_only": True,
        "live_blocked": True,
    }
    values.update(overrides)
    return FullSwapEvidenceBoundInput(**values)


def test_complete_runtime_and_book_evidence_can_satisfy_readiness() -> None:
    assessment = assess_evidence_bound_full_swap_readiness(_input())

    assert assessment.swap_ready is True
    assert assessment.blocking_reasons == ()
    assert assessment.live_execution_authorized is False


def test_unreconciled_book_is_derived_as_hard_readiness_blocker() -> None:
    assessment = assess_evidence_bound_full_swap_readiness(
        _input(
            book_reconciliation=_book(
                risk_admission_issues=("orphan_reservation:intent-1",)
            )
        )
    )

    assert assessment.swap_ready is False
    assert assessment.blocking_reasons == (
        "canonical_vnext_book_reconciled",
    )


def test_runtime_shadow_restart_and_rollback_checks_are_evidence_derived() -> None:
    assessment = assess_evidence_bound_full_swap_readiness(
        _input(
            runtime_evidence=_runtime(
                runtime_shadow_verified=False,
                restart_recovery_verified=False,
                rollback_verified=False,
                activation_evidence_complete=False,
                blocking_reasons=(
                    "phase16_runtime_shadow_not_verified",
                    "restart_recovery_not_verified",
                    "rollback_not_verified",
                ),
            )
        )
    )

    assert assessment.blocking_reasons == (
        "phase16_runtime_shadow_verified",
        "restart_recovery_verified",
        "rollback_path_verified",
    )


def test_book_reconciliation_evidence_rejects_synthetic_substitute() -> None:
    with pytest.raises(
        ValueError,
        match="synthetic book reconciliation evidence is not admissible",
    ):
        _book(synthetic=True)


def test_all_runtime_sensitive_evidence_must_share_deployed_revision() -> None:
    with pytest.raises(ValueError, match="share one deployed revision"):
        _input(
            book_reconciliation=_book(deployed_revision="different-revision")
        )
