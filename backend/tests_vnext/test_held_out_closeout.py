from __future__ import annotations

import pytest

from aether_vnext.held_out_closeout import (
    build_held_out_closeout_readiness,
)
from aether_vnext.held_out_replay_results import ReplayCoverageReport


def _manifest_report(
    *,
    canonical: int = 74,
    supplied: int = 74,
    missing: int = 0,
    folds: int = 148,
    windows: int = 74,
) -> dict[str, object]:
    return {
        "canonical_executable_route_count": canonical,
        "supplied_route_count": supplied,
        "missing_route_count": missing,
        "fold_count": folds,
        "window_count": windows,
    }


def _coverage(
    *,
    expected: int = 148,
    supplied: int = 148,
    missing: tuple[str, ...] = (),
    unexpected: tuple[str, ...] = (),
    duplicate_trades: tuple[str, ...] = (),
) -> ReplayCoverageReport:
    return ReplayCoverageReport(
        expected_work_item_count=expected,
        supplied_result_count=supplied,
        missing_work_item_ids=missing,
        unexpected_work_item_ids=unexpected,
        duplicate_trade_ids=duplicate_trades,
    )


def test_closeout_ready_only_when_manifest_and_replay_are_complete() -> None:
    result = build_held_out_closeout_readiness(
        manifest_validation_report=_manifest_report(),
        replay_coverage=_coverage(),
    )

    assert result.ready is True
    assert result.canonical_universe_complete is True
    assert result.replay_result_coverage_complete is True
    assert result.blocker_counts == ()


def test_missing_routes_are_reported_without_inventing_completion() -> None:
    result = build_held_out_closeout_readiness(
        manifest_validation_report=_manifest_report(
            supplied=70,
            missing=4,
        ),
        replay_coverage=_coverage(),
    )

    assert result.ready is False
    assert result.canonical_universe_complete is False
    assert result.blocker_counts == (
        ("held_out_manifest_missing_routes", 1),
    )


def test_incomplete_replay_coverage_is_a_distinct_blocker() -> None:
    result = build_held_out_closeout_readiness(
        manifest_validation_report=_manifest_report(),
        replay_coverage=_coverage(
            supplied=147,
            missing=("work-148",),
        ),
    )

    assert result.ready is False
    assert result.replay_result_coverage_complete is False
    assert result.blocker_counts == (
        ("held_out_replay_results_incomplete", 1),
    )


def test_empty_fold_or_window_counts_fail_closed() -> None:
    result = build_held_out_closeout_readiness(
        manifest_validation_report=_manifest_report(
            folds=0,
            windows=0,
        ),
        replay_coverage=_coverage(),
    )

    assert result.ready is False
    assert result.blocker_counts == (
        ("held_out_evidence_windows_missing", 1),
        ("held_out_fold_results_missing", 1),
    )


def test_external_blockers_are_preserved_exactly() -> None:
    result = build_held_out_closeout_readiness(
        manifest_validation_report=_manifest_report(),
        replay_coverage=_coverage(),
        extra_blockers=(
            "runtime_product_binding_missing",
            "runtime_product_binding_missing",
            "tastyfx_private_fix_spec_pending",
        ),
    )

    assert result.ready is False
    assert result.blocker_counts == (
        ("runtime_product_binding_missing", 2),
        ("tastyfx_private_fix_spec_pending", 1),
    )


def test_inconsistent_manifest_route_counts_fail_closed() -> None:
    with pytest.raises(ValueError, match="internally inconsistent"):
        build_held_out_closeout_readiness(
            manifest_validation_report=_manifest_report(
                canonical=74,
                supplied=70,
                missing=3,
            ),
            replay_coverage=_coverage(),
        )

    with pytest.raises(ValueError, match="cannot exceed"):
        build_held_out_closeout_readiness(
            manifest_validation_report=_manifest_report(
                canonical=74,
                supplied=75,
                missing=0,
            ),
            replay_coverage=_coverage(),
        )
