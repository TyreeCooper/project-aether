"""Import real held-out research evidence into the canonical vNext research ledger.

This boundary accepts only externally produced research facts. It never synthesizes
trades, fills, metrics, folds, or profitability. The manifest is fully validated
before any database mutation and can optionally require exact coverage of the
canonical forward-paper executable universe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper import parse_route_id
from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_route_requests,
)
from aether_vnext.freeze import CONFIGURATION_HASH, ResearchState
from aether_vnext.playbooks import playbook
from aether_vnext.research import (
    BacktestRun,
    FoldResult,
    HypothesisCard,
    ResearchDatasetSnapshot,
    ResearchExperiment,
)
from aether_vnext.store import VNextStore


MANIFEST_VERSION = "aether-vnext-held-out-v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HeldOutWindowRecord:
    window: EvidenceWindow
    backtest_run_id: str
    fold_result_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeldOutResearchManifest:
    manifest_version: str
    configuration_hash: str
    policy_version: str
    source_ref: str
    hypotheses: tuple[HypothesisCard, ...]
    datasets: tuple[ResearchDatasetSnapshot, ...]
    experiments: tuple[ResearchExperiment, ...]
    runs: tuple[BacktestRun, ...]
    folds: tuple[FoldResult, ...]
    windows: tuple[HeldOutWindowRecord, ...]


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _rows(payload: Mapping[str, object], name: str) -> list[dict[str, Any]]:
    value = payload.get(name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{name} entries must be JSON objects")
    return list(value)


def _strings(
    value: object,
    name: str,
    *,
    nonempty: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    rows = tuple(_text(item, name) for item in value)
    if nonempty and not rows:
        raise ValueError(f"{name} cannot be empty")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} cannot contain duplicates")
    return rows


def _utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _hash64(value: object, name: str) -> str:
    text = _text(value, name)
    if not _HASH64.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 64-hex digest")
    return text


def _sha40(value: object, name: str) -> str:
    text = _text(value, name)
    if not _SHA40.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-hex commit SHA")
    return text


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _unique_ids(rows: tuple[object, ...], field: str, label: str) -> None:
    values = tuple(str(getattr(row, field)) for row in rows)
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def parse_held_out_research_manifest(
    payload: Mapping[str, object],
) -> HeldOutResearchManifest:
    if not isinstance(payload, Mapping):
        raise ValueError("manifest must be a JSON object")

    manifest_version = _text(payload.get("manifest_version"), "manifest_version")
    if manifest_version != MANIFEST_VERSION:
        raise ValueError("unsupported held-out research manifest_version")

    configuration_hash = _hash64(
        payload.get("configuration_hash"),
        "configuration_hash",
    )
    if configuration_hash != CONFIGURATION_HASH:
        raise ValueError(
            "held-out research manifest configuration_hash is not canonical"
        )

    policy_version = _text(payload.get("policy_version"), "policy_version")
    source_ref = _text(payload.get("source_ref"), "source_ref")

    hypotheses = tuple(
        HypothesisCard(
            hypothesis_id=_text(row.get("hypothesis_id"), "hypothesis_id"),
            created_at_utc=_utc(row.get("created_at_utc"), "created_at_utc"),
            hypothesis_text=_text(
                row.get("hypothesis_text"),
                "hypothesis_text",
            ),
            economic_rationale=_text(
                row.get("economic_rationale"),
                "economic_rationale",
            ),
            mechanism_class=_text(
                row.get("mechanism_class"),
                "mechanism_class",
            ),
            eligible_assets=_strings(
                row.get("eligible_assets"),
                "eligible_assets",
            ),
            horizon=_text(row.get("horizon"), "horizon"),
            allowed_sides=_strings(
                row.get("allowed_sides"),
                "allowed_sides",
            ),
            expected_regimes=_strings(
                row.get("expected_regimes"),
                "expected_regimes",
            ),
            falsification_conditions=_strings(
                row.get("falsification_conditions"),
                "falsification_conditions",
            ),
            required_data=_strings(
                row.get("required_data"),
                "required_data",
            ),
            benchmark_ids=_strings(
                row.get("benchmark_ids"),
                "benchmark_ids",
            ),
            status=ResearchState(_text(row.get("status"), "status")),
            annotations=_strings(
                row.get("annotations", []),
                "annotations",
                nonempty=False,
            ),
        )
        for row in _rows(payload, "hypotheses")
    )

    datasets = tuple(
        ResearchDatasetSnapshot(
            dataset_snapshot_id=_text(
                row.get("dataset_snapshot_id"),
                "dataset_snapshot_id",
            ),
            created_at_utc=_utc(
                row.get("created_at_utc"),
                "created_at_utc",
            ),
            as_of_utc=_utc(row.get("as_of_utc"), "as_of_utc"),
            start_at_utc=_utc(row.get("start_at_utc"), "start_at_utc"),
            end_at_utc=_utc(row.get("end_at_utc"), "end_at_utc"),
            asset_ids=_strings(row.get("asset_ids"), "asset_ids"),
            data_version=_text(row.get("data_version"), "data_version"),
            source_registry_version=_text(
                row.get("source_registry_version"),
                "source_registry_version",
            ),
            product_registry_version=_text(
                row.get("product_registry_version"),
                "product_registry_version",
            ),
            calendar_version=_text(
                row.get("calendar_version"),
                "calendar_version",
            ),
            pit=row.get("pit") is True,
            missing_data_policy=_text(
                row.get("missing_data_policy"),
                "missing_data_policy",
            ),
            content_hash=_hash64(
                row.get("content_hash"),
                "content_hash",
            ),
        )
        for row in _rows(payload, "datasets")
    )

    experiments = tuple(
        ResearchExperiment(
            experiment_id=_text(
                row.get("experiment_id"),
                "experiment_id",
            ),
            hypothesis_id=_text(
                row.get("hypothesis_id"),
                "hypothesis_id",
            ),
            parent_experiment_id=_optional_text(
                row.get("parent_experiment_id"),
                "parent_experiment_id",
            ),
            created_at_utc=_utc(
                row.get("created_at_utc"),
                "created_at_utc",
            ),
            frozen_at_utc=(
                None
                if row.get("frozen_at_utc") is None
                else _utc(
                    row.get("frozen_at_utc"),
                    "frozen_at_utc",
                )
            ),
            research_state=ResearchState(
                _text(
                    row.get("research_state"),
                    "research_state",
                )
            ),
            parameter_spec=(
                dict(row.get("parameter_spec"))
                if isinstance(row.get("parameter_spec"), dict)
                else {}
            ),
            parameter_space_hash=_hash64(
                row.get("parameter_space_hash"),
                "parameter_space_hash",
            ),
            dataset_snapshot_id=_text(
                row.get("dataset_snapshot_id"),
                "dataset_snapshot_id",
            ),
            code_commit_sha=_sha40(
                row.get("code_commit_sha"),
                "code_commit_sha",
            ),
            configuration_hash=configuration_hash,
            owner=_text(row.get("owner"), "owner"),
            supersedes_experiment_id=_optional_text(
                row.get("supersedes_experiment_id"),
                "supersedes_experiment_id",
            ),
        )
        for row in _rows(payload, "experiments")
    )

    runs = tuple(
        BacktestRun(
            backtest_run_id=_text(
                row.get("backtest_run_id"),
                "backtest_run_id",
            ),
            experiment_id=_text(
                row.get("experiment_id"),
                "experiment_id",
            ),
            run_type=_text(row.get("run_type"), "run_type"),
            dataset_snapshot_id=_text(
                row.get("dataset_snapshot_id"),
                "dataset_snapshot_id",
            ),
            playbook_id=_text(row.get("playbook_id"), "playbook_id"),
            playbook_version=_text(
                row.get("playbook_version"),
                "playbook_version",
            ),
            code_commit_sha=_sha40(
                row.get("code_commit_sha"),
                "code_commit_sha",
            ),
            configuration_hash=configuration_hash,
            cost_model_version=_text(
                row.get("cost_model_version"),
                "cost_model_version",
            ),
            execution_model_version=_text(
                row.get("execution_model_version"),
                "execution_model_version",
            ),
            random_seed=(
                None
                if row.get("random_seed") is None
                else int(row.get("random_seed"))
            ),
            started_at_utc=_utc(
                row.get("started_at_utc"),
                "started_at_utc",
            ),
            finished_at_utc=(
                None
                if row.get("finished_at_utc") is None
                else _utc(
                    row.get("finished_at_utc"),
                    "finished_at_utc",
                )
            ),
            status=_text(row.get("status"), "status"),
            integrity_flags=_strings(
                row.get("integrity_flags", []),
                "integrity_flags",
                nonempty=False,
            ),
            metrics_json=(
                dict(row.get("metrics_json"))
                if isinstance(row.get("metrics_json"), dict)
                else {}
            ),
        )
        for row in _rows(payload, "runs")
    )

    folds = tuple(
        FoldResult(
            fold_result_id=_text(
                row.get("fold_result_id"),
                "fold_result_id",
            ),
            backtest_run_id=_text(
                row.get("backtest_run_id"),
                "backtest_run_id",
            ),
            fold_index=int(row.get("fold_index")),
            train_start_utc=_utc(
                row.get("train_start_utc"),
                "train_start_utc",
            ),
            train_end_utc=_utc(
                row.get("train_end_utc"),
                "train_end_utc",
            ),
            test_start_utc=_utc(
                row.get("test_start_utc"),
                "test_start_utc",
            ),
            test_end_utc=_utc(
                row.get("test_end_utc"),
                "test_end_utc",
            ),
            n=int(row.get("n")),
            net_pnl=float(row.get("net_pnl")),
            expectancy_r=float(row.get("expectancy_r")),
            profit_factor=float(row.get("profit_factor")),
            stop_rate=float(row.get("stop_rate")),
            max_drawdown=float(row.get("max_drawdown")),
            cost_drag=float(row.get("cost_drag")),
            benchmark_result=(
                dict(row.get("benchmark_result"))
                if isinstance(row.get("benchmark_result"), dict)
                else {}
            ),
            passed=_bool(row.get("passed"), "passed"),
            failure_reasons=_strings(
                row.get("failure_reasons", []),
                "failure_reasons",
                nonempty=False,
            ),
        )
        for row in _rows(payload, "folds")
    )

    windows = tuple(
        HeldOutWindowRecord(
            window=EvidenceWindow(
                evidence_window_id=_text(
                    row.get("evidence_window_id"),
                    "evidence_window_id",
                ),
                route_id=_text(row.get("route_id"), "route_id"),
                playbook_id=_text(
                    row.get("playbook_id"),
                    "playbook_id",
                ),
                playbook_version=_text(
                    row.get("playbook_version"),
                    "playbook_version",
                ),
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                sample_domain=SampleDomain.HELD_OUT,
                first_timestamp_utc=_utc(
                    row.get("first_timestamp_utc"),
                    "first_timestamp_utc",
                ),
                last_timestamp_utc=_utc(
                    row.get("last_timestamp_utc"),
                    "last_timestamp_utc",
                ),
                n=int(row.get("n")),
                immutable_trade_ids=_strings(
                    row.get("immutable_trade_ids"),
                    "immutable_trade_ids",
                ),
                metrics_snapshot_hash=_hash64(
                    row.get("metrics_snapshot_hash"),
                    "metrics_snapshot_hash",
                ),
                created_at_utc=_utc(
                    row.get("created_at_utc"),
                    "created_at_utc",
                ),
            ),
            backtest_run_id=_text(
                row.get("backtest_run_id"),
                "backtest_run_id",
            ),
            fold_result_ids=_strings(
                row.get("fold_result_ids"),
                "fold_result_ids",
            ),
        )
        for row in _rows(payload, "windows")
    )

    manifest = HeldOutResearchManifest(
        manifest_version=manifest_version,
        configuration_hash=configuration_hash,
        policy_version=policy_version,
        source_ref=source_ref,
        hypotheses=hypotheses,
        datasets=datasets,
        experiments=experiments,
        runs=runs,
        folds=folds,
        windows=windows,
    )
    validate_held_out_research_manifest(manifest)
    return manifest


def validate_held_out_research_manifest(
    manifest: HeldOutResearchManifest,
) -> dict[str, object]:
    _unique_ids(
        manifest.hypotheses,
        "hypothesis_id",
        "hypothesis_id",
    )
    _unique_ids(
        manifest.datasets,
        "dataset_snapshot_id",
        "dataset_snapshot_id",
    )
    _unique_ids(
        manifest.experiments,
        "experiment_id",
        "experiment_id",
    )
    _unique_ids(
        manifest.runs,
        "backtest_run_id",
        "backtest_run_id",
    )
    _unique_ids(
        manifest.folds,
        "fold_result_id",
        "fold_result_id",
    )
    _unique_ids(
        tuple(row.window for row in manifest.windows),
        "evidence_window_id",
        "evidence_window_id",
    )

    hypotheses = {
        row.hypothesis_id: row
        for row in manifest.hypotheses
    }
    datasets = {
        row.dataset_snapshot_id: row
        for row in manifest.datasets
    }
    experiments = {
        row.experiment_id: row
        for row in manifest.experiments
    }
    runs = {
        row.backtest_run_id: row
        for row in manifest.runs
    }
    folds = {
        row.fold_result_id: row
        for row in manifest.folds
    }

    for experiment in manifest.experiments:
        if experiment.research_state is not ResearchState.FROZEN:
            raise ValueError(
                "held-out import requires FROZEN research experiments"
            )
        if experiment.frozen_at_utc is None:
            raise ValueError(
                "held-out import requires frozen_at_utc"
            )
        if experiment.hypothesis_id not in hypotheses:
            raise ValueError(
                "experiment references unknown hypothesis_id"
            )
        if experiment.dataset_snapshot_id not in datasets:
            raise ValueError(
                "experiment references unknown dataset_snapshot_id"
            )

    for run in manifest.runs:
        if run.run_type.strip().lower() != "held_out":
            raise ValueError(
                "held-out import requires run_type=held_out"
            )
        if run.finished_at_utc is None:
            raise ValueError(
                "held-out import requires finished backtest runs"
            )
        if run.status not in {"COMPLETE", "FAILED_EVIDENCE"}:
            raise ValueError(
                "held-out import run status must be COMPLETE "
                "or FAILED_EVIDENCE"
            )
        experiment = experiments.get(run.experiment_id)
        if experiment is None:
            raise ValueError(
                "backtest run references unknown experiment_id"
            )
        if run.dataset_snapshot_id != experiment.dataset_snapshot_id:
            raise ValueError(
                "backtest run dataset does not match experiment dataset"
            )
        if run.code_commit_sha != experiment.code_commit_sha:
            raise ValueError(
                "backtest run commit does not match experiment commit"
            )
        if run.dataset_snapshot_id not in datasets:
            raise ValueError(
                "backtest run references unknown dataset_snapshot_id"
            )
        spec = playbook(run.playbook_id)
        if run.playbook_version != spec.version:
            raise ValueError(
                "backtest run playbook_version is not canonical"
            )

    for fold in manifest.folds:
        if fold.backtest_run_id not in runs:
            raise ValueError(
                "fold references unknown backtest_run_id"
            )

    canonical = {
        (row.route_id, row.playbook_id)
        for row in canonical_forward_paper_route_requests()
    }
    supplied: set[tuple[str, str]] = set()

    for record in manifest.windows:
        window = record.window
        key = (window.route_id, window.playbook_id)
        if key not in canonical:
            raise ValueError(
                "held-out window is not in canonical executable "
                "campaign universe"
            )
        supplied.add(key)

        run = runs.get(record.backtest_run_id)
        if run is None:
            raise ValueError(
                "held-out window references unknown backtest_run_id"
            )
        if run.playbook_id != window.playbook_id:
            raise ValueError(
                "held-out window/run playbook_id mismatch"
            )
        if run.playbook_version != window.playbook_version:
            raise ValueError(
                "held-out window/run playbook_version mismatch"
            )

        experiment = experiments[run.experiment_id]
        hypothesis = hypotheses[experiment.hypothesis_id]
        dataset = datasets[run.dataset_snapshot_id]
        asset_id, horizon, side = parse_route_id(window.route_id)
        spec = playbook(window.playbook_id)
        if window.playbook_version != spec.version:
            raise ValueError(
                "held-out window playbook_version is not canonical"
            )
        if hypothesis.status is not ResearchState.FROZEN:
            raise ValueError(
                "held-out window requires a FROZEN hypothesis"
            )
        if hypothesis.mechanism_class != spec.mechanism_class:
            raise ValueError(
                "held-out hypothesis mechanism does not match playbook"
            )
        if asset_id not in hypothesis.eligible_assets:
            raise ValueError(
                "held-out route asset absent from hypothesis"
            )
        if horizon != hypothesis.horizon:
            raise ValueError(
                "held-out route horizon does not match hypothesis"
            )
        if side not in hypothesis.allowed_sides:
            raise ValueError(
                "held-out route side absent from hypothesis"
            )
        if asset_id not in dataset.asset_ids:
            raise ValueError(
                "held-out route asset absent from PIT dataset"
            )

        selected = []
        for fold_id in record.fold_result_ids:
            fold = folds.get(fold_id)
            if fold is None:
                raise ValueError(
                    "held-out window references unknown fold_result_id"
                )
            if fold.backtest_run_id != run.backtest_run_id:
                raise ValueError(
                    "held-out fold belongs to a different backtest run"
                )
            selected.append(fold)
        selected.sort(
            key=lambda row: (
                row.test_start_utc,
                row.test_end_utc,
                row.fold_result_id,
            )
        )
        for prior, current in zip(selected, selected[1:]):
            if current.test_start_utc <= prior.test_end_utc:
                raise ValueError(
                    "held-out fold test windows overlap"
                )
        if (
            window.first_timestamp_utc
            < selected[0].test_start_utc
            or window.last_timestamp_utc
            > selected[-1].test_end_utc
        ):
            raise ValueError(
                "held-out EvidenceWindow lies outside selected "
                "fold test span"
            )

    missing = tuple(sorted(canonical - supplied))
    return {
        "manifest_version": manifest.manifest_version,
        "configuration_hash": manifest.configuration_hash,
        "policy_version": manifest.policy_version,
        "source_ref": manifest.source_ref,
        "canonical_executable_route_count": len(canonical),
        "supplied_route_count": len(supplied),
        "missing_route_count": len(missing),
        "missing_routes": [
            {
                "route_id": route_id,
                "playbook_id": playbook_id,
            }
            for route_id, playbook_id in missing
        ],
        "hypothesis_count": len(manifest.hypotheses),
        "dataset_count": len(manifest.datasets),
        "experiment_count": len(manifest.experiments),
        "run_count": len(manifest.runs),
        "fold_count": len(manifest.folds),
        "window_count": len(manifest.windows),
    }


def persist_held_out_research_manifest(
    conn: Connection,
    store: VNextStore,
    manifest: HeldOutResearchManifest,
    *,
    require_canonical_universe: bool,
) -> dict[str, object]:
    report = validate_held_out_research_manifest(manifest)
    if (
        require_canonical_universe
        and int(report["missing_route_count"]) > 0
    ):
        return {
            **report,
            "persisted": False,
        }

    policies = store.tables["policy_snapshots"]
    policy = conn.execute(
        sa.select(policies.c.configuration_hash).where(
            sa.and_(
                policies.c.configuration_hash
                == manifest.configuration_hash,
                policies.c.policy_version
                == manifest.policy_version,
            )
        )
    ).first()
    if policy is None:
        raise ValueError(
            "held-out research manifest policy_version is not present "
            "for the canonical configuration"
        )

    for row in manifest.hypotheses:
        store.record_research_hypothesis(conn, row)
    for row in manifest.datasets:
        store.record_research_dataset_snapshot(conn, row)
    for row in manifest.experiments:
        store.record_research_experiment(conn, row)
    for row in manifest.runs:
        store.record_backtest_run(conn, row)
    for row in manifest.folds:
        store.record_fold_result(conn, row)

    provenance_hashes = []
    for record in manifest.windows:
        provenance_hashes.append(
            store.record_held_out_evidence_window(
                conn,
                record.window,
                backtest_run_id=record.backtest_run_id,
                fold_result_ids=record.fold_result_ids,
            )
        )

    return {
        **report,
        "persisted": True,
        "provenance_hashes": provenance_hashes,
    }
