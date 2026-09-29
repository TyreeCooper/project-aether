from __future__ import annotations

from datetime import datetime, timezone

from aether_vnext.full_swap_readiness import (
    FullSwapReadinessInput,
    assess_full_swap_readiness,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)


def _input(**overrides) -> FullSwapReadinessInput:
    values = {
        "assessment_id": "phase17-readiness-1",
        "assessed_at_utc": T0,
        "phase16_internal_closeout_green": True,
        "phase16_runtime_shadow_verified": True,
        "vnext_ci_green": True,
        "repository_ci_green": True,
        "canonical_vnext_book_reconciled": True,
        "restart_recovery_verified": True,
        "rollback_path_verified": True,
        "legacy_runtime_authority_retirable": True,
        "paper_only": True,
        "live_blocked": True,
    }
    values.update(overrides)
    return FullSwapReadinessInput(**values)


def test_full_swap_readiness_requires_every_runtime_safety_proof() -> None:
    assessment = assess_full_swap_readiness(_input())

    assert assessment.swap_ready is True
    assert assessment.blocking_reasons == ()
    assert assessment.live_execution_authorized is False


def test_phase16_runtime_shadow_evidence_is_a_hard_cutover_blocker() -> None:
    assessment = assess_full_swap_readiness(
        _input(phase16_runtime_shadow_verified=False)
    )

    assert assessment.swap_ready is False
    assert assessment.blocking_reasons == (
        "phase16_runtime_shadow_verified",
    )
    assert assessment.live_execution_authorized is False


def test_reconciliation_restart_and_rollback_are_independent_hard_blocks() -> None:
    assessment = assess_full_swap_readiness(
        _input(
            canonical_vnext_book_reconciled=False,
            restart_recovery_verified=False,
            rollback_path_verified=False,
        )
    )

    assert assessment.swap_ready is False
    assert assessment.blocking_reasons == (
        "canonical_vnext_book_reconciled",
        "restart_recovery_verified",
        "rollback_path_verified",
    )


def test_full_swap_never_authorizes_live_execution() -> None:
    assessment = assess_full_swap_readiness(
        _input(live_blocked=False)
    )

    assert assessment.swap_ready is False
    assert "live_blocked" in assessment.blocking_reasons
    assert assessment.live_execution_authorized is False
    assert assessment.as_payload()["live_execution_authorized"] is False
