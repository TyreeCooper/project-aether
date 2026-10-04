"""Institutional Memory and P&L Attribution for AETHER vNext.

Phase 14 preserves experience without converting replay, memory, or
counterfactuals into independent strategy evidence. Historical records are
immutable, counterfactuals are hypothetical, and attribution must reconcile
without an unexplained residual.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


PNL_ATTRIBUTION_COMPONENTS = frozenset(
    {
        "alpha",
        "beta",
        "spread",
        "fees",
        "slippage",
        "adverse_selection",
        "carry_swap_funding",
        "borrow",
        "gap",
        "execution_improvement_degradation",
    }
)

FAILURE_CATEGORIES = frozenset(
    {
        "losing_mechanism_false_break",
        "abnormal_slippage_spread_widening",
        "failed_hedge_correlation_convergence",
        "rejected_duplicated_ambiguous_orders",
        "stale_malformed_data",
        "model_assumption_failure",
        "operational_incident_recovery",
    }
)

COUNTERFACTUAL_VARIATIONS = frozenset(
    {
        "stop",
        "target",
        "time_stop",
        "trailing",
        "sizing",
        "mechanism",
        "no_trade",
    }
)


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


def _canonical_tuple(name: str, values: object) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        _canonical_text(f"{name} entry", value)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class PnlAttributionComponent:
    category: str
    amount_usd: float

    def __post_init__(self) -> None:
        if self.category not in PNL_ATTRIBUTION_COMPONENTS:
            raise ValueError("invalid P&L attribution category")
        if isinstance(self.amount_usd, bool) or not math.isfinite(
            float(self.amount_usd)
        ):
            raise ValueError("amount_usd must be finite numeric")


@dataclass(frozen=True, slots=True)
class PnlAttributionRecord:
    attribution_id: str
    firm_id: str
    mechanism_id: str
    playbook_id: str
    playbook_version: str
    route_id: str
    asset_id: str
    horizon: str
    side: str
    regime_id: str
    trade_id: str
    configuration_hash: str
    net_pnl_usd: float
    components: tuple[PnlAttributionComponent, ...]
    attributed_at_utc: datetime
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "attribution_id",
            "firm_id",
            "mechanism_id",
            "playbook_id",
            "playbook_version",
            "route_id",
            "asset_id",
            "horizon",
            "side",
            "regime_id",
            "trade_id",
            "configuration_hash",
        ):
            _canonical_text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if isinstance(self.net_pnl_usd, bool) or not math.isfinite(
            float(self.net_pnl_usd)
        ):
            raise ValueError("net_pnl_usd must be finite numeric")
        if not isinstance(self.components, tuple) or not self.components:
            raise ValueError("components must be a nonempty immutable tuple")
        categories = tuple(row.category for row in self.components)
        if len(categories) != len(set(categories)):
            raise ValueError("duplicate P&L attribution category")
        attributed = sum(float(row.amount_usd) for row in self.components)
        if not math.isclose(
            attributed,
            float(self.net_pnl_usd),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "P&L attribution must reconcile with no unexplained residual"
            )
        if self.attributed_at_utc.tzinfo is None:
            raise ValueError("attributed_at_utc must be timezone-aware")
        _canonical_tuple("source_record_ids", self.source_record_ids)


@dataclass(frozen=True, slots=True)
class InstitutionalMemoryRecord:
    memory_id: str
    trade_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    configuration_hash: str
    market_state_ref: str
    information_state_ref: str
    signal_ref: str
    decision_ref: str
    expected_outcome_ref: str
    actual_outcome_ref: str
    execution_quality_ref: str
    risk_state_ref: str
    success_failure_reason: str
    lesson: str
    future_relevance: tuple[str, ...]
    occurred_at_utc: datetime
    recorded_at_utc: datetime
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "memory_id",
            "trade_id",
            "route_id",
            "playbook_id",
            "playbook_version",
            "configuration_hash",
            "market_state_ref",
            "information_state_ref",
            "signal_ref",
            "decision_ref",
            "expected_outcome_ref",
            "actual_outcome_ref",
            "execution_quality_ref",
            "risk_state_ref",
            "success_failure_reason",
            "lesson",
        ):
            _canonical_text(name, getattr(self, name))
        _canonical_tuple("future_relevance", self.future_relevance)
        _canonical_tuple("source_record_ids", self.source_record_ids)
        for name in ("occurred_at_utc", "recorded_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.recorded_at_utc < self.occurred_at_utc:
            raise ValueError("memory cannot be recorded before occurrence")


@dataclass(frozen=True, slots=True)
class FailureArchiveEntry:
    failure_id: str
    memory_id: str
    trade_id: str
    category: str
    reason: str
    recovery_lesson: str
    recorded_at_utc: datetime
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "failure_id",
            "memory_id",
            "trade_id",
            "reason",
            "recovery_lesson",
        ):
            _canonical_text(name, getattr(self, name))
        if self.category not in FAILURE_CATEGORIES:
            raise ValueError("invalid failure archive category")
        if self.recorded_at_utc.tzinfo is None:
            raise ValueError("recorded_at_utc must be timezone-aware")
        _canonical_tuple("source_record_ids", self.source_record_ids)


@dataclass(frozen=True, slots=True)
class CounterfactualReplayRecord:
    replay_id: str
    original_memory_id: str
    variation_keys: tuple[str, ...]
    hypothetical_result_ref: str
    created_at_utc: datetime
    hypothetical: bool = True
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        for name in (
            "replay_id",
            "original_memory_id",
            "hypothetical_result_ref",
        ):
            _canonical_text(name, getattr(self, name))
        variations = _canonical_tuple(
            "variation_keys",
            self.variation_keys,
        )
        if not variations:
            raise ValueError("counterfactual requires at least one variation")
        if any(
            variation not in COUNTERFACTUAL_VARIATIONS
            for variation in variations
        ):
            raise ValueError("invalid counterfactual variation")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if self.hypothetical is not True:
            raise ValueError("counterfactual replay must remain hypothetical")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "counterfactual replay cannot receive independent evidence credit"
            )


@dataclass(frozen=True, slots=True)
class ExperienceCoverage:
    historical_years: float
    unique_regimes_crises: int
    event_categories: int
    asset_event_combinations: int
    execution_failure_scenarios: int
    correlation_stress_scenarios: int
    unique_market_state_clusters: int
    forward_paper_days: int
    forward_paper_trades: int
    historical_forward_gaps: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.historical_years, bool)
            or not math.isfinite(float(self.historical_years))
            or float(self.historical_years) < 0.0
        ):
            raise ValueError("historical_years must be finite and nonnegative")
        for name in (
            "unique_regimes_crises",
            "event_categories",
            "asset_event_combinations",
            "execution_failure_scenarios",
            "correlation_stress_scenarios",
            "unique_market_state_clusters",
            "forward_paper_days",
            "forward_paper_trades",
            "historical_forward_gaps",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be a nonnegative integer")
