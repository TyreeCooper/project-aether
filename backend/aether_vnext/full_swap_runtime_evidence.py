"""Runtime evidence contracts for AETHER Phase 17 Full Swap-Out.

These records represent observed non-production evidence only. Synthetic fixtures,
unit tests, and source-code assertions cannot satisfy the deployed runtime gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _source_ids(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty immutable tuple")
    for value in values:
        _canonical_text(f"{name} entry", value)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class RuntimeShadowEvidence:
    evidence_id: str
    environment: str
    deployed_revision: str
    observed_at_utc: datetime
    floor_route_status_code: int
    dedicated_vnext_book_read: bool
    legacy_surface_available: bool
    mutation_transport_absent: bool
    second_runtime_started: bool
    paper_only: bool
    live_blocked: bool
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in ("evidence_id", "environment", "deployed_revision"):
            _canonical_text(name, getattr(self, name))
        _aware("observed_at_utc", self.observed_at_utc)
        _source_ids("source_artifact_ids", self.source_artifact_ids)
        if self.environment != "aether-vnext-burnin":
            raise ValueError("runtime shadow evidence must come from aether-vnext-burnin")
        if self.synthetic is not False:
            raise ValueError("synthetic runtime-shadow evidence is not admissible")

    @property
    def verified(self) -> bool:
        return bool(
            self.floor_route_status_code == 200
            and self.dedicated_vnext_book_read
            and self.legacy_surface_available
            and self.mutation_transport_absent
            and not self.second_runtime_started
            and self.paper_only
            and self.live_blocked
            and not self.synthetic
        )


@dataclass(frozen=True, slots=True)
class RestartScenarioEvidence:
    scenario_id: str
    scenario: str
    deployed_revision: str
    observed_at_utc: datetime
    identity_preserved: bool
    cash_preserved: bool
    margin_preserved: bool
    position_state_preserved: bool
    idempotency_preserved: bool
    reconciliation_clean: bool
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in ("scenario_id", "scenario", "deployed_revision"):
            _canonical_text(name, getattr(self, name))
        if self.scenario not in {"mid_ticket", "mid_order", "open_trade"}:
            raise ValueError("unsupported restart evidence scenario")
        _aware("observed_at_utc", self.observed_at_utc)
        _source_ids("source_artifact_ids", self.source_artifact_ids)
        if self.synthetic is not False:
            raise ValueError("synthetic restart evidence is not admissible")

    @property
    def verified(self) -> bool:
        return bool(
            self.identity_preserved
            and self.cash_preserved
            and self.margin_preserved
            and self.position_state_preserved
            and self.idempotency_preserved
            and self.reconciliation_clean
            and not self.synthetic
        )


@dataclass(frozen=True, slots=True)
class RollbackRuntimeEvidence:
    evidence_id: str
    deployed_revision: str
    observed_at_utc: datetime
    previous_paper_runtime_restored: bool
    recovery_started_offline: bool
    reconciliation_clean_before_arm: bool
    automatic_rearm_observed: bool
    operator_confirmation_required: bool
    paper_only: bool
    live_blocked: bool
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in ("evidence_id", "deployed_revision"):
            _canonical_text(name, getattr(self, name))
        _aware("observed_at_utc", self.observed_at_utc)
        _source_ids("source_artifact_ids", self.source_artifact_ids)
        if self.synthetic is not False:
            raise ValueError("synthetic rollback evidence is not admissible")

    @property
    def verified(self) -> bool:
        return bool(
            self.previous_paper_runtime_restored
            and self.recovery_started_offline
            and self.reconciliation_clean_before_arm
            and not self.automatic_rearm_observed
            and self.operator_confirmation_required
            and self.paper_only
            and self.live_blocked
            and not self.synthetic
        )


@dataclass(frozen=True, slots=True)
class Phase17RuntimeEvidenceAssessment:
    deployed_revision: str
    runtime_shadow_verified: bool
    restart_recovery_verified: bool
    rollback_verified: bool
    activation_evidence_complete: bool
    blocking_reasons: tuple[str, ...]


def assess_phase17_runtime_evidence(
    *,
    shadow: RuntimeShadowEvidence,
    restart_scenarios: tuple[RestartScenarioEvidence, ...],
    rollback: RollbackRuntimeEvidence,
) -> Phase17RuntimeEvidenceAssessment:
    """Assess one-revision runtime evidence without changing runtime authority."""
    revisions = {
        shadow.deployed_revision,
        rollback.deployed_revision,
        *(row.deployed_revision for row in restart_scenarios),
    }
    if len(revisions) != 1:
        raise ValueError("all Phase-17 runtime evidence must share one deployed revision")

    by_scenario = {row.scenario: row for row in restart_scenarios}
    if len(by_scenario) != len(restart_scenarios):
        raise ValueError("restart evidence cannot duplicate a scenario")
    required = {"mid_ticket", "mid_order", "open_trade"}
    restart_verified = (
        set(by_scenario) == required
        and all(by_scenario[name].verified for name in required)
    )

    blockers: list[str] = []
    if not shadow.verified:
        blockers.append("phase16_runtime_shadow_not_verified")
    if not restart_verified:
        blockers.append("restart_recovery_not_verified")
    if not rollback.verified:
        blockers.append("rollback_not_verified")

    return Phase17RuntimeEvidenceAssessment(
        deployed_revision=shadow.deployed_revision,
        runtime_shadow_verified=shadow.verified,
        restart_recovery_verified=restart_verified,
        rollback_verified=rollback.verified,
        activation_evidence_complete=not blockers,
        blocking_reasons=tuple(blockers),
    )
