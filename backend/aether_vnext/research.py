"""AETHER vNext Alpha Factory / research contracts from Pre-Code Freeze F-006."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any

from aether_vnext.freeze import EvidenceState, ResearchState

ALPHA_FACTORY_RUN_TYPES = frozenset(
    {
        "backtest",
        "walk_forward",
        "held_out",
        "parameter_sensitivity",
        "cost_stress",
    }
)

EVIDENCE_BEARING_RUN_TYPES = frozenset(
    {
        "walk_forward",
        "held_out",
        "cost_stress",
    }
)


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

    def __post_init__(self) -> None:
        required = {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_text": self.hypothesis_text,
            "economic_rationale": self.economic_rationale,
            "mechanism_class": self.mechanism_class,
            "horizon": self.horizon,
        }
        for name, value in required.items():
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if not isinstance(self.status, ResearchState):
            raise ValueError("status must be a ResearchState")
        for name in (
            "eligible_assets",
            "allowed_sides",
            "expected_regimes",
            "falsification_conditions",
            "required_data",
            "benchmark_ids",
            "annotations",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be an immutable tuple")
            if any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                for value in values
            ):
                raise ValueError(f"{name} must contain canonical text")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} cannot contain duplicates")
        if not self.eligible_assets:
            raise ValueError("eligible_assets cannot be empty")
        if any(value != value.lower() for value in self.eligible_assets):
            raise ValueError("eligible_assets must contain canonical asset IDs")
        if not self.allowed_sides:
            raise ValueError("allowed_sides cannot be empty")
        if not self.benchmark_ids:
            raise ValueError("benchmark_ids cannot be empty")


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

    def __post_init__(self) -> None:
        for name in (
            "experiment_id",
            "hypothesis_id",
            "parameter_space_hash",
            "dataset_snapshot_id",
            "code_commit_sha",
            "configuration_hash",
            "owner",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name in ("parent_experiment_id", "supersedes_experiment_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text when present")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if self.frozen_at_utc is not None:
            if self.frozen_at_utc.tzinfo is None:
                raise ValueError("frozen_at_utc must be timezone-aware")
            if self.frozen_at_utc < self.created_at_utc:
                raise ValueError("frozen_at_utc cannot precede created_at_utc")
        if (
            self.research_state is ResearchState.FROZEN
            and self.frozen_at_utc is None
        ):
            raise ValueError("FROZEN research requires frozen_at_utc")


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
        for name in (
            "dataset_snapshot_id",
            "data_version",
            "source_registry_version",
            "product_registry_version",
            "calendar_version",
            "missing_data_policy",
            "content_hash",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name in (
            "created_at_utc",
            "as_of_utc",
            "start_at_utc",
            "end_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.start_at_utc > self.end_at_utc:
            raise ValueError("dataset start_at_utc cannot follow end_at_utc")
        if self.end_at_utc > self.as_of_utc:
            raise ValueError("dataset cannot contain information after as_of_utc")
        if not isinstance(self.asset_ids, tuple) or not self.asset_ids:
            raise ValueError("asset_ids must be a nonempty immutable tuple")
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or value != value.lower()
            for value in self.asset_ids
        ):
            raise ValueError("asset_ids must contain canonical asset IDs")
        if len(self.asset_ids) != len(set(self.asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates")


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

    def __post_init__(self) -> None:
        for name in (
            "backtest_run_id",
            "experiment_id",
            "run_type",
            "dataset_snapshot_id",
            "playbook_id",
            "playbook_version",
            "code_commit_sha",
            "configuration_hash",
            "cost_model_version",
            "execution_model_version",
            "status",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if self.run_type not in ALPHA_FACTORY_RUN_TYPES:
            raise ValueError(
                "run_type must be one of the source-bound Alpha Factory modes"
            )
        if self.started_at_utc.tzinfo is None:
            raise ValueError("started_at_utc must be timezone-aware")
        if self.finished_at_utc is not None:
            if self.finished_at_utc.tzinfo is None:
                raise ValueError("finished_at_utc must be timezone-aware")
            if self.finished_at_utc < self.started_at_utc:
                raise ValueError("finished_at_utc cannot precede started_at_utc")


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
        for name in ("fold_result_id", "backtest_run_id"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if (
            not isinstance(self.fold_index, int)
            or isinstance(self.fold_index, bool)
            or self.fold_index < 0
        ):
            raise ValueError("fold_index must be a nonnegative integer")
        if (
            not isinstance(self.n, int)
            or isinstance(self.n, bool)
            or self.n < 0
        ):
            raise ValueError("n must be a nonnegative integer")
        for name in (
            "train_start_utc",
            "train_end_utc",
            "test_start_utc",
            "test_end_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not (
            self.train_start_utc <= self.train_end_utc
            < self.test_start_utc <= self.test_end_utc
        ):
            raise ValueError("fold windows must be chronological and non-overlapping")
        for name in ("net_pnl", "expectancy_r", "max_drawdown", "cost_drag"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if float(self.max_drawdown) < 0.0:
            raise ValueError("max_drawdown cannot be negative")
        if float(self.cost_drag) < 0.0:
            raise ValueError("cost_drag cannot be negative")
        profit_factor = float(self.profit_factor)
        if math.isnan(profit_factor) or profit_factor < 0.0:
            raise ValueError("profit_factor must be nonnegative and not NaN")
        stop_rate = float(self.stop_rate)
        if not math.isfinite(stop_rate) or not 0.0 <= stop_rate <= 1.0:
            raise ValueError("stop_rate must be in [0,1]")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be boolean")


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

    def __post_init__(self) -> None:
        for name in (
            "promotion_id",
            "route_id",
            "playbook_version",
            "review_card_id",
            "evidence_window_id",
            "reviewer",
            "approver",
            "decision_reason",
            "configuration_hash",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name in ("from_evidence_state", "to_evidence_state"):
            if not isinstance(getattr(self, name), EvidenceState):
                raise ValueError(f"{name} must be an EvidenceState")
        if not isinstance(self.n_reset, bool):
            raise ValueError("n_reset must be boolean")
        if self.supersedes is not None and (
            not isinstance(self.supersedes, str)
            or not self.supersedes
            or self.supersedes != self.supersedes.strip()
        ):
            raise ValueError("supersedes must be canonical text when present")
        if self.decided_at_utc.tzinfo is None:
            raise ValueError("decided_at_utc must be timezone-aware")
