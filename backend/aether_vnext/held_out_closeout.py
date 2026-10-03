"""Read-only HELD_OUT closeout readiness aggregation for Phase 18.

This module does not persist research, create evidence, run providers, start a
campaign, or mutate any evidence state. It combines two already-validated facts:

- the canonical held-out manifest validation report;
- deterministic replay-result coverage.

The output makes remaining Phase 18 blockers explicit without weakening them.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from aether_vnext.held_out_replay_results import ReplayCoverageReport


@dataclass(frozen=True, slots=True)
class HeldOutCloseoutReadiness:
    ready: bool
    canonical_universe_complete: bool
    replay_result_coverage_complete: bool
    canonical_executable_route_count: int
    supplied_route_count: int
    missing_route_count: int
    expected_work_item_count: int
    supplied_result_count: int
    fold_count: int
    window_count: int
    blocker_counts: tuple[tuple[str, int], ...]


def _nonnegative_int(report: Mapping[str, object], key: str) -> int:
    value = report.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a nonnegative integer")
    return value


def build_held_out_closeout_readiness(
    *,
    manifest_validation_report: Mapping[str, object],
    replay_coverage: ReplayCoverageReport,
    extra_blockers: Iterable[str] = (),
) -> HeldOutCloseoutReadiness:
    """Aggregate exact held-out closeout facts into one deterministic report."""
    if not isinstance(manifest_validation_report, Mapping):
        raise ValueError("manifest_validation_report must be a mapping")

    canonical_routes = _nonnegative_int(
        manifest_validation_report,
        "canonical_executable_route_count",
    )
    supplied_routes = _nonnegative_int(
        manifest_validation_report,
        "supplied_route_count",
    )
    missing_routes = _nonnegative_int(
        manifest_validation_report,
        "missing_route_count",
    )
    fold_count = _nonnegative_int(
        manifest_validation_report,
        "fold_count",
    )
    window_count = _nonnegative_int(
        manifest_validation_report,
        "window_count",
    )

    if supplied_routes > canonical_routes:
        raise ValueError("supplied_route_count cannot exceed canonical route count")
    if missing_routes != canonical_routes - supplied_routes:
        raise ValueError("manifest route counts are internally inconsistent")
    if replay_coverage.expected_work_item_count < 0:
        raise ValueError("expected_work_item_count cannot be negative")
    if replay_coverage.supplied_result_count < 0:
        raise ValueError("supplied_result_count cannot be negative")

    blockers: list[str] = []
    if missing_routes:
        blockers.append("held_out_manifest_missing_routes")
    if not replay_coverage.complete:
        blockers.append("held_out_replay_results_incomplete")
    if fold_count <= 0:
        blockers.append("held_out_fold_results_missing")
    if window_count <= 0:
        blockers.append("held_out_evidence_windows_missing")

    blockers.extend(
        value
        for raw in extra_blockers
        if (value := str(raw).strip())
    )
    counts = Counter(blockers)

    canonical_complete = (
        canonical_routes > 0
        and supplied_routes == canonical_routes
        and missing_routes == 0
    )
    replay_complete = replay_coverage.complete

    ready = bool(
        canonical_complete
        and replay_complete
        and fold_count > 0
        and window_count > 0
        and not blockers
    )

    return HeldOutCloseoutReadiness(
        ready=ready,
        canonical_universe_complete=canonical_complete,
        replay_result_coverage_complete=replay_complete,
        canonical_executable_route_count=canonical_routes,
        supplied_route_count=supplied_routes,
        missing_route_count=missing_routes,
        expected_work_item_count=replay_coverage.expected_work_item_count,
        supplied_result_count=replay_coverage.supplied_result_count,
        fold_count=fold_count,
        window_count=window_count,
        blocker_counts=tuple(sorted(counts.items())),
    )
