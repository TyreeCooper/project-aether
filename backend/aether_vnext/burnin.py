"""Firm-level profitability burn-in readiness gate for AETHER vNext.

P11 is evidence, not a timer invented by code. The source requires sustained operation,
no unresolved accounting/model defects, and sufficient OOS/trusted-route evidence, but
does not bind universal duration or route-count thresholds. Those two judgments must
therefore be supplied by explicit versioned policies.

A profitability-ready result is observational only. It never authorizes live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class BurnInReadinessInput:
    assessment_id: str
    readiness_policy_version: str
    firm_snapshot_hash: str
    burn_in_start_at_utc: datetime
    burn_in_end_at_utc: datetime
    as_of_utc: datetime
    sustained_operation_satisfied: bool | None
    sustained_operation_policy_version: str | None
    oos_trusted_sufficiency_satisfied: bool | None
    oos_trusted_sufficiency_policy_version: str | None
    active_route_count: int
    trusted_route_count: int
    oos_positive_route_count: int
    unresolved_accounting_defects: tuple[str, ...]
    unresolved_model_defects: tuple[str, ...]
    architecture_execution_green: bool
    versioned_net_cost_evidence_complete: bool
    held_out_positive_expectancy_complete: bool
    realistic_execution_complete: bool
    declared_regimes_complete: bool
    survivable_risk_complete: bool
    portfolio_constraints_complete: bool
    decay_bench_mechanism_operational: bool
    material_change_lineage_complete: bool
    full_history_retained: bool
    live_blocked: bool

    def __post_init__(self) -> None:
        for name in (
            "assessment_id",
            "readiness_policy_version",
            "firm_snapshot_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        for name in (
            "burn_in_start_at_utc",
            "burn_in_end_at_utc",
            "as_of_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.burn_in_start_at_utc > self.burn_in_end_at_utc:
            raise ValueError("burn-in start cannot follow burn-in end")
        if self.burn_in_end_at_utc > self.as_of_utc:
            raise ValueError("burn-in end cannot be after as_of_utc")
        for name in (
            "active_route_count",
            "trusted_route_count",
            "oos_positive_route_count",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.trusted_route_count > self.active_route_count:
            raise ValueError("trusted_route_count cannot exceed active_route_count")
        if self.oos_positive_route_count > self.active_route_count:
            raise ValueError("oos_positive_route_count cannot exceed active_route_count")

        if self.sustained_operation_satisfied is not None:
            if not str(self.sustained_operation_policy_version or "").strip():
                raise ValueError(
                    "sustained_operation_policy_version required for bound decision"
                )
        if self.oos_trusted_sufficiency_satisfied is not None:
            if not str(
                self.oos_trusted_sufficiency_policy_version or ""
            ).strip():
                raise ValueError(
                    "oos_trusted_sufficiency_policy_version required for bound decision"
                )


@dataclass(frozen=True, slots=True)
class ProfitabilityReadinessAssessment:
    assessment_id: str
    readiness_policy_version: str
    firm_snapshot_hash: str
    burn_in_start_at_utc: datetime
    burn_in_end_at_utc: datetime
    as_of_utc: datetime
    burn_in_duration_s: float
    active_route_count: int
    trusted_route_count: int
    oos_positive_route_count: int
    sustained_operation_satisfied: bool | None
    sustained_operation_policy_version: str | None
    oos_trusted_sufficiency_satisfied: bool | None
    oos_trusted_sufficiency_policy_version: str | None
    profitability_ready: bool
    live_execution_authorized: bool
    blocking_reasons: tuple[str, ...]
    unresolved_rules: tuple[str, ...]
    unresolved_accounting_defects: tuple[str, ...]
    unresolved_model_defects: tuple[str, ...]
    evidence_checks: dict[str, bool]

    def as_payload(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "readiness_policy_version": self.readiness_policy_version,
            "firm_snapshot_hash": self.firm_snapshot_hash,
            "burn_in_start_at_utc": self.burn_in_start_at_utc.isoformat(),
            "burn_in_end_at_utc": self.burn_in_end_at_utc.isoformat(),
            "as_of_utc": self.as_of_utc.isoformat(),
            "burn_in_duration_s": self.burn_in_duration_s,
            "active_route_count": self.active_route_count,
            "trusted_route_count": self.trusted_route_count,
            "oos_positive_route_count": self.oos_positive_route_count,
            "sustained_operation_satisfied": self.sustained_operation_satisfied,
            "sustained_operation_policy_version": (
                self.sustained_operation_policy_version
            ),
            "oos_trusted_sufficiency_satisfied": (
                self.oos_trusted_sufficiency_satisfied
            ),
            "oos_trusted_sufficiency_policy_version": (
                self.oos_trusted_sufficiency_policy_version
            ),
            "profitability_ready": self.profitability_ready,
            "live_execution_authorized": False,
            "blocking_reasons": list(self.blocking_reasons),
            "unresolved_rules": list(self.unresolved_rules),
            "unresolved_accounting_defects": list(
                self.unresolved_accounting_defects
            ),
            "unresolved_model_defects": list(self.unresolved_model_defects),
            "evidence_checks": dict(self.evidence_checks),
        }


def assess_profitability_readiness(
    value: BurnInReadinessInput,
) -> ProfitabilityReadinessAssessment:
    unresolved: list[str] = []
    blocked: list[str] = []

    if value.sustained_operation_satisfied is None:
        unresolved.append("burn_in_duration_sufficiency_policy_unbound")
    elif not value.sustained_operation_satisfied:
        blocked.append("sustained_operation_not_satisfied")

    if value.oos_trusted_sufficiency_satisfied is None:
        unresolved.append("oos_trusted_route_sufficiency_policy_unbound")
    elif not value.oos_trusted_sufficiency_satisfied:
        blocked.append("oos_trusted_route_evidence_insufficient")

    if value.active_route_count <= 0:
        blocked.append("no_active_routes")
    if value.unresolved_accounting_defects:
        blocked.append("unresolved_accounting_defects")
    if value.unresolved_model_defects:
        blocked.append("unresolved_model_defects")

    checks = {
        "architecture_execution_green": value.architecture_execution_green,
        "versioned_net_cost_evidence_complete": (
            value.versioned_net_cost_evidence_complete
        ),
        "held_out_positive_expectancy_complete": (
            value.held_out_positive_expectancy_complete
        ),
        "realistic_execution_complete": value.realistic_execution_complete,
        "declared_regimes_complete": value.declared_regimes_complete,
        "survivable_risk_complete": value.survivable_risk_complete,
        "portfolio_constraints_complete": value.portfolio_constraints_complete,
        "decay_bench_mechanism_operational": (
            value.decay_bench_mechanism_operational
        ),
        "material_change_lineage_complete": (
            value.material_change_lineage_complete
        ),
        "full_history_retained": value.full_history_retained,
        "live_blocked": value.live_blocked,
    }
    for name, passed in checks.items():
        if not passed:
            blocked.append(name)

    ready = not unresolved and not blocked
    return ProfitabilityReadinessAssessment(
        assessment_id=value.assessment_id,
        readiness_policy_version=value.readiness_policy_version,
        firm_snapshot_hash=value.firm_snapshot_hash,
        burn_in_start_at_utc=value.burn_in_start_at_utc,
        burn_in_end_at_utc=value.burn_in_end_at_utc,
        as_of_utc=value.as_of_utc,
        burn_in_duration_s=(
            value.burn_in_end_at_utc - value.burn_in_start_at_utc
        ).total_seconds(),
        active_route_count=value.active_route_count,
        trusted_route_count=value.trusted_route_count,
        oos_positive_route_count=value.oos_positive_route_count,
        sustained_operation_satisfied=value.sustained_operation_satisfied,
        sustained_operation_policy_version=(
            value.sustained_operation_policy_version
        ),
        oos_trusted_sufficiency_satisfied=(
            value.oos_trusted_sufficiency_satisfied
        ),
        oos_trusted_sufficiency_policy_version=(
            value.oos_trusted_sufficiency_policy_version
        ),
        profitability_ready=ready,
        live_execution_authorized=False,
        blocking_reasons=tuple(dict.fromkeys(blocked)),
        unresolved_rules=tuple(dict.fromkeys(unresolved)),
        unresolved_accounting_defects=tuple(
            value.unresolved_accounting_defects
        ),
        unresolved_model_defects=tuple(value.unresolved_model_defects),
        evidence_checks=checks,
    )
