"""Profitability evidence object required by AETHER Master Part IV."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable


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
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
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


class SampleDomain(StrEnum):
    IN_SAMPLE = "in_sample"
    HELD_OUT = "held_out"
    PAPER_FORWARD = "paper_forward"
    EXECUTION_VALIDATION = "execution_validation"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    evidence_window_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    policy_version: str
    configuration_hash: str
    sample_domain: SampleDomain
    first_timestamp_utc: datetime
    last_timestamp_utc: datetime
    n: int
    immutable_trade_ids: tuple[str, ...]
    metrics_snapshot_hash: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        required = {
            "evidence_window_id": self.evidence_window_id,
            "route_id": self.route_id,
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
            "policy_version": self.policy_version,
            "configuration_hash": self.configuration_hash,
            "metrics_snapshot_hash": self.metrics_snapshot_hash,
        }
        for name, value in required.items():
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name, value in (
            ("first_timestamp_utc", self.first_timestamp_utc),
            ("last_timestamp_utc", self.last_timestamp_utc),
            ("created_at_utc", self.created_at_utc),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.first_timestamp_utc > self.last_timestamp_utc:
            raise ValueError("EvidenceWindow timestamps are reversed")
        if not isinstance(self.immutable_trade_ids, tuple):
            raise ValueError("immutable_trade_ids must be an immutable tuple")
        raw_ids = self.immutable_trade_ids
        if (
            not raw_ids
            or any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                for value in raw_ids
            )
        ):
            raise ValueError("immutable_trade_ids must contain canonical IDs")
        ids = tuple(raw_ids)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate immutable_trade_id in EvidenceWindow")
        if not isinstance(self.n, int) or isinstance(self.n, bool):
            raise ValueError("EvidenceWindow n must be an integer")
        if self.n != len(ids):
            raise ValueError("EvidenceWindow n must equal immutable_trade_ids length")
        if self.n <= 0:
            raise ValueError("EvidenceWindow n must be positive")


def _window_family(window: EvidenceWindow) -> tuple[str, ...]:
    return (
        window.route_id,
        window.playbook_id,
        window.playbook_version,
        window.policy_version,
        window.configuration_hash,
        window.sample_domain.value,
    )


def independent_trade_ids(
    windows: Iterable[EvidenceWindow],
) -> tuple[str, ...]:
    rows = tuple(windows)
    if not rows:
        return ()
    family = _window_family(rows[0])
    for row in rows[1:]:
        if _window_family(row) != family:
            raise ValueError(
                "EvidenceWindows from different sample/version/config families "
                "cannot merge"
            )
    return tuple(
        sorted(
            {
                trade_id
                for row in rows
                for trade_id in row.immutable_trade_ids
            }
        )
    )


def independent_n(
    windows: Iterable[EvidenceWindow],
) -> int:
    return len(independent_trade_ids(windows))


def strategy_evidence_n(
    windows: Iterable[EvidenceWindow],
) -> int:
    rows = tuple(windows)
    if not rows:
        return 0
    ids = independent_trade_ids(rows)
    if rows[0].sample_domain is SampleDomain.EXECUTION_VALIDATION:
        return 0
    return len(ids)
