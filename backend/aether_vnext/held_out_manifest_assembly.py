"""Assemble canonical HELD_OUT research manifests from already-built objects.

This is a packaging/validation boundary only. It does not create hypotheses,
datasets, experiments, runs, trades, fold metrics, evidence windows, or database rows.

Inputs must already be canonical objects produced by the reviewed research path.
The existing held_out_import validator remains the source of manifest-integrity truth.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.held_out_evidence_window import (
    HeldOutEvidenceWindowAssembly,
)
from aether_vnext.held_out_fold_assembly import HeldOutFoldAssembly
from aether_vnext.held_out_import import (
    MANIFEST_VERSION,
    HeldOutResearchManifest,
    HeldOutWindowRecord,
    validate_held_out_research_manifest,
)
from aether_vnext.research import (
    BacktestRun,
    HypothesisCard,
    ResearchDatasetSnapshot,
    ResearchExperiment,
)


@dataclass(frozen=True, slots=True)
class HeldOutManifestAssembly:
    manifest: HeldOutResearchManifest
    validation_report: dict[str, object]


def _canonical_text(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


def _require_nonempty_tuple(value: tuple[object, ...], name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a non-empty immutable tuple")


def assemble_held_out_research_manifest(
    *,
    policy_version: str,
    configuration_hash: str,
    source_ref: str,
    hypotheses: tuple[HypothesisCard, ...],
    datasets: tuple[ResearchDatasetSnapshot, ...],
    experiments: tuple[ResearchExperiment, ...],
    runs: tuple[BacktestRun, ...],
    fold_assemblies: tuple[HeldOutFoldAssembly, ...],
    window_assemblies: tuple[HeldOutEvidenceWindowAssembly, ...],
) -> HeldOutManifestAssembly:
    """Package already-canonical research objects and run the canonical validator."""
    policy = _canonical_text(policy_version, "policy_version")
    config = _canonical_text(configuration_hash, "configuration_hash")
    source = _canonical_text(source_ref, "source_ref")
    if config != CONFIGURATION_HASH:
        raise ValueError(
            "held-out manifest assembly requires canonical configuration_hash"
        )

    for value, name in (
        (hypotheses, "hypotheses"),
        (datasets, "datasets"),
        (experiments, "experiments"),
        (runs, "runs"),
        (fold_assemblies, "fold_assemblies"),
        (window_assemblies, "window_assemblies"),
    ):
        _require_nonempty_tuple(value, name)

    for experiment in experiments:
        if experiment.configuration_hash != config:
            raise ValueError("experiment configuration_hash mismatch")
    for run in runs:
        if run.configuration_hash != config:
            raise ValueError("run configuration_hash mismatch")
    for assembly in window_assemblies:
        if assembly.window.configuration_hash != config:
            raise ValueError("window configuration_hash mismatch")
        if assembly.window.policy_version != policy:
            raise ValueError("window policy_version mismatch")

    folds = tuple(row.fold_result for row in fold_assemblies)
    windows = tuple(
        HeldOutWindowRecord(
            window=row.window,
            backtest_run_id=row.backtest_run_id,
            fold_result_ids=row.fold_result_ids,
        )
        for row in window_assemblies
    )

    manifest = HeldOutResearchManifest(
        manifest_version=MANIFEST_VERSION,
        configuration_hash=config,
        policy_version=policy,
        source_ref=source,
        hypotheses=hypotheses,
        datasets=datasets,
        experiments=experiments,
        runs=runs,
        folds=folds,
        windows=windows,
    )
    report = validate_held_out_research_manifest(manifest)
    return HeldOutManifestAssembly(
        manifest=manifest,
        validation_report=report,
    )
