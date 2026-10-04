from __future__ import annotations

from aether_vnext.market_fabric_closeout import (
    DataRightsContract,
    RecoveryEvidence,
    RecoveryPolicy,
    RightsState,
    evaluate_market_fabric_closeout,
)


def _rights() -> tuple[DataRightsContract, ...]:
    return (
        DataRightsContract(
            provider_id="provider-a",
            economic_source_id="source-a",
            state=RightsState.APPROVED,
            storage_allowed=True,
            redistribution_allowed=False,
            display_allowed=True,
            derived_use_allowed=True,
            review_reference="rights-review-001",
        ),
    )


def test_closeout_refuses_to_guess_rpo_rto() -> None:
    result = evaluate_market_fabric_closeout(
        rights=_rights(),
        recovery_policy=RecoveryPolicy(
            policy_version="dr-v1",
            target_rpo_seconds=None,
            target_rto_seconds=None,
            multi_region_enabled=False,
        ),
        recovery_evidence=None,
    )

    assert result.ready is False
    assert "recovery_targets_unbound" in result.blockers
    assert result.live_authorized is False
    assert result.live_blocked is True


def test_unreviewed_provider_rights_block_operational_closeout() -> None:
    rights = (
        DataRightsContract(
            provider_id="provider-a",
            economic_source_id="source-a",
            state=RightsState.UNREVIEWED,
            storage_allowed=None,
            redistribution_allowed=None,
            display_allowed=None,
            derived_use_allowed=None,
            review_reference=None,
        ),
    )
    evidence = RecoveryEvidence(
        evidence_id="dr-1",
        measured_rpo_seconds=30,
        measured_rto_seconds=60,
        backup_restore_tested=True,
        state_hash_equivalent=True,
        single_writer_fencing_proven=True,
        multi_region_fencing_proven=None,
    )
    result = evaluate_market_fabric_closeout(
        rights=rights,
        recovery_policy=RecoveryPolicy(
            policy_version="dr-v1",
            target_rpo_seconds=60,
            target_rto_seconds=120,
            multi_region_enabled=False,
        ),
        recovery_evidence=evidence,
    )

    assert result.ready is False
    assert "provider-a:data_rights_unreviewed" in result.blockers


def test_measured_restore_inside_bound_targets_can_close_repository_gate() -> None:
    evidence = RecoveryEvidence(
        evidence_id="dr-1",
        measured_rpo_seconds=30,
        measured_rto_seconds=60,
        backup_restore_tested=True,
        state_hash_equivalent=True,
        single_writer_fencing_proven=True,
        multi_region_fencing_proven=None,
    )
    result = evaluate_market_fabric_closeout(
        rights=_rights(),
        recovery_policy=RecoveryPolicy(
            policy_version="dr-v1",
            target_rpo_seconds=60,
            target_rto_seconds=120,
            multi_region_enabled=False,
        ),
        recovery_evidence=evidence,
    )

    assert result.ready is True
    assert result.blockers == ()
    assert result.paper_only is True
    assert result.live_blocked is True
    assert result.live_authorized is False
