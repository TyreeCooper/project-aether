"""MF-15 disaster recovery, data-rights, and operational closeout contracts.

Closeout is evidence-driven. RPO/RTO targets are explicit business inputs, not
guessed defaults. Data rights are reviewed per provider/economic source. Passing this
module never authorizes LIVE execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RightsState(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    RESTRICTED = "RESTRICTED"
    APPROVED = "APPROVED"


@dataclass(frozen=True, slots=True)
class DataRightsContract:
    provider_id: str
    economic_source_id: str
    state: RightsState
    storage_allowed: bool | None
    redistribution_allowed: bool | None
    display_allowed: bool | None
    derived_use_allowed: bool | None
    review_reference: str | None

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.economic_source_id.strip():
            raise ValueError("economic_source_id is required")

    @property
    def reviewed(self) -> bool:
        return (
            self.state is not RightsState.UNREVIEWED
            and bool(str(self.review_reference or "").strip())
        )

    def blockers_for(
        self,
        *,
        require_storage: bool,
        require_display: bool,
        require_derived: bool,
        require_redistribution: bool = False,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.reviewed:
            blockers.append("data_rights_unreviewed")
            return tuple(blockers)
        if require_storage and self.storage_allowed is not True:
            blockers.append("storage_right_not_confirmed")
        if require_display and self.display_allowed is not True:
            blockers.append("display_right_not_confirmed")
        if require_derived and self.derived_use_allowed is not True:
            blockers.append("derived_use_right_not_confirmed")
        if require_redistribution and self.redistribution_allowed is not True:
            blockers.append("redistribution_right_not_confirmed")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    policy_version: str
    target_rpo_seconds: int | None
    target_rto_seconds: int | None
    multi_region_enabled: bool

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.target_rpo_seconds is not None and self.target_rpo_seconds < 0:
            raise ValueError("target_rpo_seconds cannot be negative")
        if self.target_rto_seconds is not None and self.target_rto_seconds < 0:
            raise ValueError("target_rto_seconds cannot be negative")

    @property
    def bound(self) -> bool:
        return self.target_rpo_seconds is not None and self.target_rto_seconds is not None


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    evidence_id: str
    measured_rpo_seconds: int
    measured_rto_seconds: int
    backup_restore_tested: bool
    state_hash_equivalent: bool
    single_writer_fencing_proven: bool
    multi_region_fencing_proven: bool | None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")
        if self.measured_rpo_seconds < 0 or self.measured_rto_seconds < 0:
            raise ValueError("measured recovery times cannot be negative")


@dataclass(frozen=True, slots=True)
class MarketFabricCloseout:
    ready: bool
    blockers: tuple[str, ...]
    paper_only: bool = True
    live_blocked: bool = True
    live_authorized: bool = False


def evaluate_market_fabric_closeout(
    *,
    rights: tuple[DataRightsContract, ...],
    recovery_policy: RecoveryPolicy,
    recovery_evidence: RecoveryEvidence | None,
    require_display: bool = True,
    require_storage: bool = True,
    require_derived: bool = True,
) -> MarketFabricCloseout:
    blockers: list[str] = []
    if not rights:
        blockers.append("provider_data_rights_missing")
    for contract in rights:
        for blocker in contract.blockers_for(
            require_storage=require_storage,
            require_display=require_display,
            require_derived=require_derived,
        ):
            blockers.append(f"{contract.provider_id}:{blocker}")

    if not recovery_policy.bound:
        blockers.append("recovery_targets_unbound")
    if recovery_evidence is None:
        blockers.append("recovery_evidence_missing")
    elif recovery_policy.bound:
        assert recovery_policy.target_rpo_seconds is not None
        assert recovery_policy.target_rto_seconds is not None
        if recovery_evidence.measured_rpo_seconds > recovery_policy.target_rpo_seconds:
            blockers.append("rpo_target_missed")
        if recovery_evidence.measured_rto_seconds > recovery_policy.target_rto_seconds:
            blockers.append("rto_target_missed")
        if not recovery_evidence.backup_restore_tested:
            blockers.append("backup_restore_not_tested")
        if not recovery_evidence.state_hash_equivalent:
            blockers.append("restore_state_hash_mismatch")
        if not recovery_evidence.single_writer_fencing_proven:
            blockers.append("single_writer_fencing_unproven")
        if (
            recovery_policy.multi_region_enabled
            and recovery_evidence.multi_region_fencing_proven is not True
        ):
            blockers.append("multi_region_fencing_unproven")

    return MarketFabricCloseout(
        ready=not blockers,
        blockers=tuple(sorted(set(blockers))),
    )
