"""AETHER vNext Alpha Factory / research contracts from Pre-Code Freeze F-006."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aether_vnext.freeze import EvidenceState, ResearchState


@dataclass(frozen=True, slots=True)
class HypothesisCard:
    hypothesis_id: str
    created_at_utc: datetime
    hypothesis_text: str
    economic_rationale: str
    mechanism_class: str
    eligible_assets: tuple[str, ...]
    horizon: str
    allowed_sides: tuple[str, ...]
    expected_regimes: tuple[str, ...]
    falsification_conditions: tuple[str, ...]
    required_data: tuple[str, ...]
    benchmark_ids: tuple[str, ...]
    status: ResearchState
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchExperiment:
    experiment_id: str
    hypothesis_id: str
    parent_experiment_id: str | None
    created_at_utc: datetime
    frozen_at_utc: datetime | None
    research_state: ResearchState
    parameter_spec: dict[str, Any]
    parameter_space_hash: str
    dataset_snapshot_id: str
    code_commit_sha: str
    configuration_hash: str
    owner: str
    supersedes_experiment_id: str | None


@dataclass(frozen=True, slots=True)
class ResearchDatasetSnapshot:
    dataset_snapshot_id: str
    created_at_utc: datetime
    as_of_utc: datetime
    start_at_utc: datetime
    end_at_utc: datetime
    asset_ids: tuple[str, ...]
    data_version: str
    source_registry_version: str
    product_registry_version: str
    calendar_version: str
    pit: bool
    missing_data_policy: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.pit is not True:
            raise ValueError("ResearchDatasetSnapshot requires PIT=true")


@dataclass(frozen=True, slots=True)
class BacktestRun:
    backtest_run_id: str
    experiment_id: str
    run_type: str
    dataset_snapshot_id: str
    playbook_id: str
    playbook_version: str
    code_commit_sha: str
    configuration_hash: str
    cost_model_version: str
    execution_model_version: str
    random_seed: int | None
    started_at_utc: datetime
    finished_at_utc: datetime | None
    status: str
    integrity_flags: tuple[str, ...] = ()
    metrics_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold_result_id: str
    backtest_run_id: str
    fold_index: int
    train_start_utc: datetime
    train_end_utc: datetime
    test_start_utc: datetime
    test_end_utc: datetime
    n: int
    net_pnl: float
    expectancy_r: float
    profit_factor: float
    stop_rate: float
    max_drawdown: float
    cost_drag: float
    benchmark_result: dict[str, Any]
    passed: bool
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (
            self.train_start_utc <= self.train_end_utc
            < self.test_start_utc <= self.test_end_utc
        ):
            raise ValueError("fold windows must be chronological and non-overlapping")


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    evidence_window_id: str
    route_id: str
    playbook_version: str
    policy_configuration_hash_family: str
    sample_domain: str
    first_timestamp_utc: datetime
    last_timestamp_utc: datetime
    n: int
    immutable_trade_ids: tuple[str, ...]
    metrics_snapshot_hash: str

    VALID_SAMPLE_DOMAINS = frozenset(
        {"in_sample", "held_out", "paper_forward", "execution_validation", "live"}
    )

    def __post_init__(self) -> None:
        if self.sample_domain not in self.VALID_SAMPLE_DOMAINS:
            raise ValueError(f"invalid sample_domain: {self.sample_domain}")
        if self.n != len(self.immutable_trade_ids):
            raise ValueError("evidence n must equal immutable trade-id count")


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    promotion_id: str
    route_id: str
    playbook_version: str
    from_evidence_state: EvidenceState
    to_evidence_state: EvidenceState
    review_card_id: str
    evidence_window_id: str
    reviewer: str
    approver: str
    decided_at_utc: datetime
    decision_reason: str
    configuration_hash: str
    n_reset: bool
    supersedes: str | None
