from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.restart_evidence_compare import (
    compare_restart_evidence_snapshots,
)
from aether_vnext.restart_evidence_snapshot import RestartEvidenceSnapshot
from aether_vnext.store import canonical_payload_hash


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 22, 0, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "event_count": 17,
        "broker_ledgers": [
            {
                "broker_account_id": "kraken_paper",
                "cash_available_usd": 3900.0,
                "cash_reserved_usd": 100.0,
                "margin_used_usd": 0.0,
                "margin_available_usd": 4000.0,
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_usd": 0.0,
                "fees_accrued_usd": 0.0,
                "carry_accrued_usd": 0.0,
                "settled_cash_usd": 4000.0,
                "reconciliation_state": "clean",
                "row_version": 2,
            }
        ],
        "in_flight_setups": [{"setup_id": "setup-1", "state": "FIRE"}],
        "in_flight_tickets": [{"ticket_id": "ticket-1", "state": "READY"}],
        "in_flight_order_intents": [
            {
                "order_intent_id": "intent-1",
                "state": "SUBMITTED",
                "idempotency_key": "idem-1",
            }
        ],
        "active_positions": [],
        "open_trade_records": [],
        "consumed_signals": [],
        "mutation_idempotency": [
            {
                "idempotency_key": "idem-1",
                "mutation_type": "OPEN",
                "aggregate_type": "order_intent",
                "aggregate_id": "intent-1",
                "result_payload_hash": "hash-1",
            }
        ],
        "risk_admission_issues": [],
    }


def _snapshot(
    *,
    snapshot_id: str,
    payload: dict[str, object] | None = None,
    at=T0,
    revision="revision-1",
    scenario="mid_order",
    blockers: tuple[str, ...] = (),
) -> RestartEvidenceSnapshot:
    value = deepcopy(payload if payload is not None else _payload())
    return RestartEvidenceSnapshot(
        snapshot_id=snapshot_id,
        deployed_revision=revision,
        scenario=scenario,
        observed_at_utc=at,
        state_payload=value,
        state_payload_hash=canonical_payload_hash(value),
        reconciliation_blockers=blockers,
        source_artifact_ids=(f"artifact-{snapshot_id}",),
        synthetic=False,
    )


def test_identical_before_after_snapshots_produce_verified_restart_evidence() -> None:
    result = compare_restart_evidence_snapshots(
        scenario_id="restart-mid-order-1",
        before=_snapshot(snapshot_id="before"),
        after=_snapshot(
            snapshot_id="after",
            at=T0 + timedelta(seconds=10),
        ),
    )

    assert result.verified is True
    assert result.event_count_preserved is True
    assert result.evidence.identity_preserved is True
    assert result.evidence.cash_preserved is True
    assert result.evidence.margin_preserved is True
    assert result.evidence.position_state_preserved is True
    assert result.evidence.idempotency_preserved is True
    assert result.evidence.reconciliation_clean is True
    assert result.evidence.source_artifact_ids == (
        "artifact-before",
        "artifact-after",
    )


def test_restart_event_mutation_breaks_identity_preservation() -> None:
    after = _payload()
    after["event_count"] = 18

    result = compare_restart_evidence_snapshots(
        scenario_id="restart-mid-order-events",
        before=_snapshot(snapshot_id="before"),
        after=_snapshot(
            snapshot_id="after",
            payload=after,
            at=T0 + timedelta(seconds=10),
        ),
    )

    assert result.event_count_preserved is False
    assert result.evidence.identity_preserved is False
    assert result.verified is False


def test_restart_cash_and_margin_drift_are_independent_failures() -> None:
    after = _payload()
    ledger = after["broker_ledgers"][0]
    ledger["cash_available_usd"] = 3899.0
    ledger["margin_used_usd"] = 1.0

    result = compare_restart_evidence_snapshots(
        scenario_id="restart-ledger-drift",
        before=_snapshot(snapshot_id="before"),
        after=_snapshot(
            snapshot_id="after",
            payload=after,
            at=T0 + timedelta(seconds=10),
        ),
    )

    assert result.evidence.cash_preserved is False
    assert result.evidence.margin_preserved is False
    assert result.verified is False


def test_restart_position_or_idempotency_drift_fails_closed() -> None:
    after = _payload()
    after["active_positions"] = [
        {
            "position_key": "btc:daily_swing",
            "trade_id": "trade-unexpected",
        }
    ]
    after["mutation_idempotency"] = []

    result = compare_restart_evidence_snapshots(
        scenario_id="restart-state-drift",
        before=_snapshot(snapshot_id="before"),
        after=_snapshot(
            snapshot_id="after",
            payload=after,
            at=T0 + timedelta(seconds=10),
        ),
    )

    assert result.evidence.position_state_preserved is False
    assert result.evidence.idempotency_preserved is False
    assert result.verified is False


def test_restart_reconciliation_blocker_prevents_verified_evidence() -> None:
    result = compare_restart_evidence_snapshots(
        scenario_id="restart-blocked",
        before=_snapshot(snapshot_id="before"),
        after=_snapshot(
            snapshot_id="after",
            at=T0 + timedelta(seconds=10),
            blockers=("stale_order_intents_present",),
        ),
    )

    assert result.evidence.reconciliation_clean is False
    assert result.verified is False


def test_restart_snapshots_must_share_revision_and_scenario() -> None:
    with pytest.raises(ValueError, match="share one deployed revision"):
        compare_restart_evidence_snapshots(
            scenario_id="restart-bad-revision",
            before=_snapshot(snapshot_id="before"),
            after=_snapshot(
                snapshot_id="after",
                revision="revision-2",
                at=T0 + timedelta(seconds=10),
            ),
        )

    with pytest.raises(ValueError, match="share one scenario"):
        compare_restart_evidence_snapshots(
            scenario_id="restart-bad-scenario",
            before=_snapshot(snapshot_id="before"),
            after=_snapshot(
                snapshot_id="after",
                scenario="open_trade",
                at=T0 + timedelta(seconds=10),
            ),
        )
