"""Profitability evidence object required by AETHER Master Part IV."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CostSensitivity:
    base: dict[str, Any]
    plus25: dict[str, Any]
    plus50: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProfitabilityEvidence:
    evidence_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    policy_version: str
    configuration_hash: str
    data_version: str
    fill_model_version: str
    fee_schedule_version: str
    in_sample_window: dict[str, Any] | None
    oos_windows: tuple[dict[str, Any], ...]
    n_trades: int
    net_expectancy_usd: float
    profit_factor: float
    win_rate: float
    avg_win_usd: float
    avg_loss_usd: float
    stop_rate: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    median_duration_s: float
    capture_efficiency: float
    cost_sensitivity: CostSensitivity
    regime_matrix: dict[str, Any]
    benchmark_result: dict[str, Any]
    capacity_result: dict[str, Any]
    portfolio_contribution: dict[str, Any]
    model_risks: tuple[str, ...]
    verdict: str
    reviewer: str
    as_of_utc: datetime
