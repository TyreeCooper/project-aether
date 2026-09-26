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

    def __post_init__(self) -> None:
        required_text = {
            "evidence_id": self.evidence_id,
            "route_id": self.route_id,
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
            "policy_version": self.policy_version,
            "configuration_hash": self.configuration_hash,
            "data_version": self.data_version,
            "fill_model_version": self.fill_model_version,
            "fee_schedule_version": self.fee_schedule_version,
            "verdict": self.verdict,
            "reviewer": self.reviewer,
        }
        for name, value in required_text.items():
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if int(self.n_trades) < 0:
            raise ValueError("n_trades cannot be negative")
        if not 0.0 <= float(self.win_rate) <= 1.0:
            raise ValueError("win_rate must be in [0,1]")
        if not 0.0 <= float(self.stop_rate) <= 1.0:
            raise ValueError("stop_rate must be in [0,1]")
        if float(self.median_duration_s) < 0.0:
            raise ValueError("median_duration_s cannot be negative")
