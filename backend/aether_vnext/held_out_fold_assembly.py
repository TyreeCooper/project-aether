"""Assemble canonical HELD_OUT fold records from real replay trade outcomes.

This boundary reuses AETHER's existing profitability metrics. It does not synthesize
trades, benchmark evidence, R outcomes, or pass/fail verdicts.

Callers must supply:
- the exact deterministic replay work item and fold geometry;
- real immutable trade outcomes;
- per-trade net R values from the reviewed research path;
- benchmark evidence;
- explicit pass/fail and terminal replay status.

The resulting FoldResult is suitable for the existing held-out manifest/import path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Mapping

from aether_vnext.held_out_replay_results import (
    HeldOutReplayResultRecord,
    ReplayResultStatus,
    bind_replay_result,
)
from aether_vnext.held_out_research_runner import (
    HeldOutFoldPlan,
    HeldOutReplayWorkItem,
)
from aether_vnext.profitability import EconomicTrade, RouteMetrics, route_metrics
from aether_vnext.research import FoldResult


@dataclass(frozen=True, slots=True)
class ReplayTradeOutcome:
    trade_id: str
    opened_at_utc: datetime
    closed_at_utc: datetime
    gross_pnl_usd: float
    base_cost_usd: float
    net_r: float
    stopped: bool = False
    capture_efficiency: float | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trade_id, str)
            or not self.trade_id
            or self.trade_id != self.trade_id.strip()
        ):
            raise ValueError("trade_id must be canonical text")
        for name in ("opened_at_utc", "closed_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.closed_at_utc < self.opened_at_utc:
            raise ValueError("closed_at_utc cannot precede opened_at_utc")
        for name in ("gross_pnl_usd", "base_cost_usd", "net_r"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if float(self.base_cost_usd) < 0.0:
            raise ValueError("base_cost_usd cannot be negative")
        if not isinstance(self.stopped, bool):
            raise ValueError("stopped must be boolean")
        if self.capture_efficiency is not None and not math.isfinite(
            float(self.capture_efficiency)
        ):
            raise ValueError("capture_efficiency must be finite when present")

    def economic_trade(self) -> EconomicTrade:
        return EconomicTrade(
            trade_id=self.trade_id,
            gross_pnl_usd=float(self.gross_pnl_usd),
            base_cost_usd=float(self.base_cost_usd),
            duration_s=(
                self.closed_at_utc - self.opened_at_utc
            ).total_seconds(),
            stopped=self.stopped,
            capture_efficiency=(
                None
                if self.capture_efficiency is None
                else float(self.capture_efficiency)
            ),
        )


@dataclass(frozen=True, slots=True)
class HeldOutFoldAssembly:
    work_item_id: str
    fold_result: FoldResult
    replay_result: HeldOutReplayResultRecord
    metrics: RouteMetrics
    immutable_trade_ids: tuple[str, ...]


def _canonical_text_tuple(
    values: tuple[str, ...],
    *,
    name: str,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
        ):
            raise ValueError(f"{name} must contain canonical text")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


def _validate_fold_matches_work_item(
    work_item: HeldOutReplayWorkItem,
    fold: HeldOutFoldPlan,
) -> None:
    if fold.fold_index != work_item.fold_index:
        raise ValueError("fold_index does not match replay work item")
    if fold.test_start_utc != work_item.test_start_utc:
        raise ValueError("fold test_start_utc does not match replay work item")
    if fold.test_end_utc != work_item.test_end_utc:
        raise ValueError("fold test_end_utc does not match replay work item")


def _fold_result_id(
    *,
    work_item: HeldOutReplayWorkItem,
    backtest_run_id: str,
    immutable_trade_ids: tuple[str, ...],
) -> str:
    raw = json.dumps(
        {
            "work_item_id": work_item.work_item_id,
            "backtest_run_id": backtest_run_id,
            "route_id": work_item.route_id,
            "playbook_id": work_item.playbook_id,
            "playbook_version": work_item.playbook_version,
            "fold_index": work_item.fold_index,
            "dataset_snapshot_id": work_item.dataset_snapshot_id,
            "dataset_content_hash": work_item.dataset_content_hash,
            "code_commit_sha": work_item.code_commit_sha,
            "configuration_hash": work_item.configuration_hash,
            "immutable_trade_ids": list(immutable_trade_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def assemble_held_out_fold(
    work_item: HeldOutReplayWorkItem,
    fold: HeldOutFoldPlan,
    *,
    backtest_run_id: str,
    trades: tuple[ReplayTradeOutcome, ...],
    replay_status: ReplayResultStatus,
    benchmark_result: Mapping[str, object],
    passed: bool,
    failure_reasons: tuple[str, ...] = (),
) -> HeldOutFoldAssembly:
    """Assemble one route x fold result from reviewed real trade outcomes."""
    if (
        not isinstance(backtest_run_id, str)
        or not backtest_run_id
        or backtest_run_id != backtest_run_id.strip()
    ):
        raise ValueError("backtest_run_id must be canonical text")
    if not isinstance(trades, tuple):
        raise ValueError("trades must be an immutable tuple")
    if not isinstance(benchmark_result, Mapping):
        raise ValueError("benchmark_result must be a mapping")
    if not isinstance(passed, bool):
        raise ValueError("passed must be boolean")
    reasons = _canonical_text_tuple(
        failure_reasons,
        name="failure_reasons",
    )
    if passed and reasons:
        raise ValueError("passed fold cannot contain failure_reasons")
    if passed and replay_status is not ReplayResultStatus.COMPLETE:
        raise ValueError(
            "passed fold requires COMPLETE replay status"
        )
    if not passed and replay_status is ReplayResultStatus.COMPLETE:
        raise ValueError(
            "failed fold requires FAILED_EVIDENCE replay status"
        )

    _validate_fold_matches_work_item(work_item, fold)

    trade_ids = tuple(row.trade_id for row in trades)
    if len(trade_ids) != len(set(trade_ids)):
        raise ValueError("duplicate trade_id in held-out fold")

    for row in trades:
        if row.opened_at_utc < work_item.test_start_utc:
            raise ValueError("trade opens before held-out test window")
        if row.closed_at_utc > work_item.test_end_utc:
            raise ValueError("trade closes after held-out test window")

    economic_trades = tuple(row.economic_trade() for row in trades)
    metrics = route_metrics(economic_trades, cost_multiplier=1.0)
    expectancy_r = (
        sum(float(row.net_r) for row in trades) / len(trades)
        if trades
        else 0.0
    )

    fold_result = FoldResult(
        fold_result_id=_fold_result_id(
            work_item=work_item,
            backtest_run_id=backtest_run_id,
            immutable_trade_ids=trade_ids,
        ),
        backtest_run_id=backtest_run_id,
        fold_index=fold.fold_index,
        train_start_utc=fold.train_start_utc,
        train_end_utc=fold.train_end_utc,
        test_start_utc=fold.test_start_utc,
        test_end_utc=fold.test_end_utc,
        n=metrics.n,
        net_pnl=metrics.total_net_pnl_usd,
        expectancy_r=expectancy_r,
        profit_factor=metrics.profit_factor,
        stop_rate=metrics.stop_rate,
        max_drawdown=metrics.max_drawdown_usd,
        cost_drag=metrics.total_cost_usd,
        benchmark_result=dict(benchmark_result),
        passed=passed,
        failure_reasons=reasons,
    )
    replay_result = bind_replay_result(
        work_item,
        status=replay_status,
        immutable_trade_ids=trade_ids,
    )
    return HeldOutFoldAssembly(
        work_item_id=work_item.work_item_id,
        fold_result=fold_result,
        replay_result=replay_result,
        metrics=metrics,
        immutable_trade_ids=trade_ids,
    )
