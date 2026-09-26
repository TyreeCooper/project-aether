"""Deterministic profitability metrics, cost stress, and benchmark-path integrity.

This module intentionally does not invent a universal "not worse than baseline"
scalar criterion. The frozen source requires candidate and baseline to share the
same data/fill/cost path and to retain benchmark evidence, but it does not bind one
cross-product comparison formula. Review therefore receives the exact comparable
metrics plus an explicit unresolved-comparison marker until source authority binds
that final criterion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from statistics import median
from typing import Iterable

from aether_vnext.evidence import CostSensitivity, SampleDomain


@dataclass(frozen=True, slots=True)
class EconomicTrade:
    trade_id: str
    gross_pnl_usd: float
    base_cost_usd: float
    duration_s: float
    stopped: bool = False
    capture_efficiency: float | None = None

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id is required")
        for name, value in (
            ("gross_pnl_usd", self.gross_pnl_usd),
            ("base_cost_usd", self.base_cost_usd),
            ("duration_s", self.duration_s),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if float(self.base_cost_usd) < 0.0:
            raise ValueError("base_cost_usd cannot be negative")
        if float(self.duration_s) < 0.0:
            raise ValueError("duration_s cannot be negative")
        if self.capture_efficiency is not None:
            if not math.isfinite(float(self.capture_efficiency)):
                raise ValueError("capture_efficiency must be finite")


@dataclass(frozen=True, slots=True)
class EconomicPath:
    dataset_snapshot_id: str
    data_version: str
    fill_model_version: str
    fee_schedule_version: str
    configuration_hash: str
    playbook_version: str
    sample_domain: SampleDomain
    first_timestamp_utc: datetime
    last_timestamp_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "dataset_snapshot_id",
            "data_version",
            "fill_model_version",
            "fee_schedule_version",
            "configuration_hash",
            "playbook_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.first_timestamp_utc.tzinfo is None:
            raise ValueError("first_timestamp_utc must be timezone-aware")
        if self.last_timestamp_utc.tzinfo is None:
            raise ValueError("last_timestamp_utc must be timezone-aware")
        if self.first_timestamp_utc > self.last_timestamp_utc:
            raise ValueError("economic path timestamps are reversed")


@dataclass(frozen=True, slots=True)
class RouteMetrics:
    n: int
    total_gross_pnl_usd: float
    total_cost_usd: float
    total_net_pnl_usd: float
    net_expectancy_usd: float
    profit_factor: float
    win_rate: float
    avg_win_usd: float
    avg_loss_usd: float
    stop_rate: float
    max_drawdown_usd: float
    median_duration_s: float
    capture_efficiency: float | None


@dataclass(frozen=True, slots=True)
class CostStressProfile:
    base: RouteMetrics
    plus25: RouteMetrics
    plus50: RouteMetrics

    def as_evidence_cost_sensitivity(self) -> CostSensitivity:
        def payload(metrics: RouteMetrics) -> dict[str, float | int | None]:
            return {
                "n": metrics.n,
                "total_gross_pnl_usd": metrics.total_gross_pnl_usd,
                "total_cost_usd": metrics.total_cost_usd,
                "total_net_pnl_usd": metrics.total_net_pnl_usd,
                "net_expectancy_usd": metrics.net_expectancy_usd,
                "profit_factor": metrics.profit_factor,
                "win_rate": metrics.win_rate,
                "avg_win_usd": metrics.avg_win_usd,
                "avg_loss_usd": metrics.avg_loss_usd,
                "stop_rate": metrics.stop_rate,
                "max_drawdown_usd": metrics.max_drawdown_usd,
                "median_duration_s": metrics.median_duration_s,
                "capture_efficiency": metrics.capture_efficiency,
            }
        return CostSensitivity(
            base=payload(self.base),
            plus25=payload(self.plus25),
            plus50=payload(self.plus50),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    benchmark_id: str
    candidate_path: EconomicPath
    baseline_path: EconomicPath
    candidate: CostStressProfile
    baseline: CostStressProfile
    comparison_rule_bound: bool
    not_worse_than_baseline: bool | None
    unresolved_reason: str | None


def _profit_factor(net_values: tuple[float, ...]) -> float:
    gross_profit = sum(value for value in net_values if value > 0.0)
    gross_loss = -sum(value for value in net_values if value < 0.0)
    if gross_loss == 0.0:
        if gross_profit > 0.0:
            return math.inf
        return 0.0
    return gross_profit / gross_loss


def _max_drawdown(net_values: tuple[float, ...]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def route_metrics(
    trades: Iterable[EconomicTrade],
    *,
    cost_multiplier: float,
) -> RouteMetrics:
    rows = tuple(trades)
    if not math.isfinite(float(cost_multiplier)) or float(cost_multiplier) < 0.0:
        raise ValueError("cost_multiplier must be finite and nonnegative")
    ids = [row.trade_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate trade_id in profitability sample")

    stressed_costs = tuple(
        float(row.base_cost_usd) * float(cost_multiplier)
        for row in rows
    )
    net_values = tuple(
        float(row.gross_pnl_usd) - cost
        for row, cost in zip(rows, stressed_costs)
    )
    n = len(rows)
    wins = tuple(value for value in net_values if value > 0.0)
    losses = tuple(value for value in net_values if value < 0.0)
    capture = tuple(
        float(row.capture_efficiency)
        for row in rows
        if row.capture_efficiency is not None
    )

    return RouteMetrics(
        n=n,
        total_gross_pnl_usd=sum(float(row.gross_pnl_usd) for row in rows),
        total_cost_usd=sum(stressed_costs),
        total_net_pnl_usd=sum(net_values),
        net_expectancy_usd=(sum(net_values) / n if n else 0.0),
        profit_factor=_profit_factor(net_values),
        win_rate=(len(wins) / n if n else 0.0),
        avg_win_usd=(sum(wins) / len(wins) if wins else 0.0),
        avg_loss_usd=(sum(losses) / len(losses) if losses else 0.0),
        stop_rate=(
            sum(1 for row in rows if row.stopped) / n
            if n else 0.0
        ),
        max_drawdown_usd=_max_drawdown(net_values),
        median_duration_s=(
            float(median(float(row.duration_s) for row in rows))
            if rows else 0.0
        ),
        capture_efficiency=(
            sum(capture) / len(capture)
            if capture else None
        ),
    )


def cost_stress_profile(
    trades: Iterable[EconomicTrade],
) -> CostStressProfile:
    rows = tuple(trades)
    return CostStressProfile(
        base=route_metrics(rows, cost_multiplier=1.00),
        plus25=route_metrics(rows, cost_multiplier=1.25),
        plus50=route_metrics(rows, cost_multiplier=1.50),
    )


def assert_same_economic_path(
    candidate: EconomicPath,
    baseline: EconomicPath,
) -> None:
    fields = (
        "dataset_snapshot_id",
        "data_version",
        "fill_model_version",
        "fee_schedule_version",
        "configuration_hash",
        "playbook_version",
        "sample_domain",
        "first_timestamp_utc",
        "last_timestamp_utc",
    )
    mismatches = [
        name
        for name in fields
        if getattr(candidate, name) != getattr(baseline, name)
    ]
    if mismatches:
        raise ValueError(
            "candidate/baseline economic path mismatch: "
            + ",".join(mismatches)
        )


def compare_to_benchmark(
    *,
    benchmark_id: str,
    candidate_path: EconomicPath,
    baseline_path: EconomicPath,
    candidate_trades: Iterable[EconomicTrade],
    baseline_trades: Iterable[EconomicTrade],
) -> BenchmarkComparison:
    if not str(benchmark_id).strip():
        raise ValueError("benchmark_id is required")
    assert_same_economic_path(candidate_path, baseline_path)
    return BenchmarkComparison(
        benchmark_id=str(benchmark_id),
        candidate_path=candidate_path,
        baseline_path=baseline_path,
        candidate=cost_stress_profile(tuple(candidate_trades)),
        baseline=cost_stress_profile(tuple(baseline_trades)),
        comparison_rule_bound=False,
        not_worse_than_baseline=None,
        unresolved_reason=(
            "source binds same-path benchmark evaluation but does not bind "
            "one universal scalar 'not worse than baseline' comparator"
        ),
    )


def benchmark_result_payload(
    comparison: BenchmarkComparison,
) -> dict[str, object]:
    def metrics_payload(metrics: RouteMetrics) -> dict[str, object]:
        return {
            "n": metrics.n,
            "net_expectancy_usd": metrics.net_expectancy_usd,
            "profit_factor": metrics.profit_factor,
            "total_net_pnl_usd": metrics.total_net_pnl_usd,
            "total_cost_usd": metrics.total_cost_usd,
            "max_drawdown_usd": metrics.max_drawdown_usd,
            "stop_rate": metrics.stop_rate,
        }

    return {
        "benchmark_id": comparison.benchmark_id,
        "comparison_rule_bound": comparison.comparison_rule_bound,
        "not_worse_than_baseline": comparison.not_worse_than_baseline,
        "unresolved_reason": comparison.unresolved_reason,
        "sample_domain": comparison.candidate_path.sample_domain.value,
        "dataset_snapshot_id": comparison.candidate_path.dataset_snapshot_id,
        "candidate": {
            "base": metrics_payload(comparison.candidate.base),
            "plus25": metrics_payload(comparison.candidate.plus25),
            "plus50": metrics_payload(comparison.candidate.plus50),
        },
        "baseline": {
            "base": metrics_payload(comparison.baseline.base),
            "plus25": metrics_payload(comparison.baseline.plus25),
            "plus50": metrics_payload(comparison.baseline.plus50),
        },
    }
