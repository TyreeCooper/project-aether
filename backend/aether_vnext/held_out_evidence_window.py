"""Assemble canonical HELD_OUT EvidenceWindow records from fold assemblies.

This is an aggregation boundary only. It does not create trades, folds, benchmark
facts, pass/fail verdicts, or database rows.

Inputs must already be canonical HeldOutFoldAssembly objects from real replay
outcomes. The assembler enforces one route/playbook/run family, non-overlapping
held-out fold windows, globally unique immutable trade IDs, and deterministic
metrics identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Any

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.held_out_fold_assembly import HeldOutFoldAssembly


@dataclass(frozen=True, slots=True)
class HeldOutEvidenceWindowAssembly:
    window: EvidenceWindow
    backtest_run_id: str
    fold_result_ids: tuple[str, ...]
    replay_result_hashes: tuple[str, ...]


def _canonical_text(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


def _stable_number(value: float) -> float | str:
    number = float(value)
    if math.isnan(number):
        raise ValueError("metrics cannot contain NaN")
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    return number


def _fold_metrics_payload(row: HeldOutFoldAssembly) -> dict[str, Any]:
    fold = row.fold_result
    return {
        "fold_result_id": fold.fold_result_id,
        "backtest_run_id": fold.backtest_run_id,
        "fold_index": fold.fold_index,
        "train_start_utc": fold.train_start_utc.isoformat(),
        "train_end_utc": fold.train_end_utc.isoformat(),
        "test_start_utc": fold.test_start_utc.isoformat(),
        "test_end_utc": fold.test_end_utc.isoformat(),
        "n": fold.n,
        "net_pnl": _stable_number(fold.net_pnl),
        "expectancy_r": _stable_number(fold.expectancy_r),
        "profit_factor": _stable_number(fold.profit_factor),
        "stop_rate": _stable_number(fold.stop_rate),
        "max_drawdown": _stable_number(fold.max_drawdown),
        "cost_drag": _stable_number(fold.cost_drag),
        "benchmark_result": fold.benchmark_result,
        "passed": fold.passed,
        "failure_reasons": list(fold.failure_reasons),
        "replay_result_hash": row.replay_result.result_hash,
        "replay_status": row.replay_result.status.value,
        "immutable_trade_ids": list(row.immutable_trade_ids),
    }


def held_out_metrics_snapshot_hash(
    folds: tuple[HeldOutFoldAssembly, ...],
) -> str:
    if not folds:
        raise ValueError("at least one held-out fold assembly is required")
    ordered = tuple(
        sorted(
            folds,
            key=lambda row: (
                row.fold_result.test_start_utc,
                row.fold_result.test_end_utc,
                row.fold_result.fold_index,
                row.fold_result.fold_result_id,
            ),
        )
    )
    raw = json.dumps(
        [_fold_metrics_payload(row) for row in ordered],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _evidence_window_id(
    *,
    route_id: str,
    playbook_id: str,
    playbook_version: str,
    policy_version: str,
    configuration_hash: str,
    backtest_run_id: str,
    fold_result_ids: tuple[str, ...],
    immutable_trade_ids: tuple[str, ...],
    metrics_snapshot_hash: str,
) -> str:
    raw = json.dumps(
        {
            "route_id": route_id,
            "playbook_id": playbook_id,
            "playbook_version": playbook_version,
            "policy_version": policy_version,
            "configuration_hash": configuration_hash,
            "backtest_run_id": backtest_run_id,
            "fold_result_ids": list(fold_result_ids),
            "immutable_trade_ids": list(immutable_trade_ids),
            "metrics_snapshot_hash": metrics_snapshot_hash,
            "sample_domain": SampleDomain.HELD_OUT.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def assemble_held_out_evidence_window(
    folds: tuple[HeldOutFoldAssembly, ...],
    *,
    policy_version: str,
    configuration_hash: str,
    created_at_utc: datetime,
) -> HeldOutEvidenceWindowAssembly:
    """Aggregate canonical fold outputs into one HELD_OUT evidence window."""
    if not isinstance(folds, tuple) or not folds:
        raise ValueError("folds must be a non-empty immutable tuple")
    policy = _canonical_text(policy_version, "policy_version")
    config = _canonical_text(configuration_hash, "configuration_hash")
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")

    ordered = tuple(
        sorted(
            folds,
            key=lambda row: (
                row.fold_result.test_start_utc,
                row.fold_result.test_end_utc,
                row.fold_result.fold_index,
                row.fold_result.fold_result_id,
            ),
        )
    )

    first = ordered[0]
    route_id = first.replay_result.route_id
    playbook_id = first.replay_result.playbook_id
    playbook_version = first.replay_result.playbook_version
    backtest_run_id = first.fold_result.backtest_run_id

    fold_ids: list[str] = []
    replay_hashes: list[str] = []
    trade_ids: list[str] = []
    seen_fold_indices: set[int] = set()
    seen_trade_ids: set[str] = set()

    prior_end: datetime | None = None
    for row in ordered:
        fold = row.fold_result
        replay = row.replay_result

        if fold.backtest_run_id != backtest_run_id:
            raise ValueError("held-out folds must share one backtest_run_id")
        if replay.route_id != route_id:
            raise ValueError("held-out folds must share one route_id")
        if replay.playbook_id != playbook_id:
            raise ValueError("held-out folds must share one playbook_id")
        if replay.playbook_version != playbook_version:
            raise ValueError("held-out folds must share one playbook_version")
        if replay.fold_index != fold.fold_index:
            raise ValueError("replay result fold_index mismatch")
        if fold.n != len(row.immutable_trade_ids):
            raise ValueError("fold n must equal immutable trade-id count")
        if fold.fold_index in seen_fold_indices:
            raise ValueError("duplicate fold_index in evidence window")
        seen_fold_indices.add(fold.fold_index)

        if prior_end is not None and fold.test_start_utc <= prior_end:
            raise ValueError(
                "held-out fold test windows must not overlap"
            )
        prior_end = fold.test_end_utc

        fold_ids.append(fold.fold_result_id)
        replay_hashes.append(replay.result_hash)
        for trade_id in row.immutable_trade_ids:
            if trade_id in seen_trade_ids:
                raise ValueError(
                    "immutable trade ID appears in multiple held-out folds"
                )
            seen_trade_ids.add(trade_id)
            trade_ids.append(trade_id)

    if not trade_ids:
        raise ValueError(
            "HELD_OUT EvidenceWindow requires at least one immutable trade"
        )

    first_timestamp = ordered[0].fold_result.test_start_utc
    last_timestamp = ordered[-1].fold_result.test_end_utc
    if created_at_utc < last_timestamp:
        raise ValueError(
            "created_at_utc cannot precede held-out evidence window end"
        )

    fold_result_ids = tuple(fold_ids)
    immutable_trade_ids = tuple(trade_ids)
    metrics_hash = held_out_metrics_snapshot_hash(ordered)

    window = EvidenceWindow(
        evidence_window_id=_evidence_window_id(
            route_id=route_id,
            playbook_id=playbook_id,
            playbook_version=playbook_version,
            policy_version=policy,
            configuration_hash=config,
            backtest_run_id=backtest_run_id,
            fold_result_ids=fold_result_ids,
            immutable_trade_ids=immutable_trade_ids,
            metrics_snapshot_hash=metrics_hash,
        ),
        route_id=route_id,
        playbook_id=playbook_id,
        playbook_version=playbook_version,
        policy_version=policy,
        configuration_hash=config,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=first_timestamp,
        last_timestamp_utc=last_timestamp,
        n=len(immutable_trade_ids),
        immutable_trade_ids=immutable_trade_ids,
        metrics_snapshot_hash=metrics_hash,
        created_at_utc=created_at_utc,
    )

    return HeldOutEvidenceWindowAssembly(
        window=window,
        backtest_run_id=backtest_run_id,
        fold_result_ids=fold_result_ids,
        replay_result_hashes=tuple(replay_hashes),
    )
