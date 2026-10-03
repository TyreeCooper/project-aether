"""Derive canonical Phase-17 restart evidence from before/after snapshots."""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.full_swap_runtime_evidence import RestartScenarioEvidence
from aether_vnext.restart_evidence_snapshot import RestartEvidenceSnapshot


_IDENTITY_SECTIONS = (
    "in_flight_setups",
    "in_flight_tickets",
    "in_flight_order_intents",
    "consumed_signals",
)
_POSITION_SECTIONS = ("active_positions", "open_trade_records")
_IDEMPOTENCY_SECTIONS = ("mutation_idempotency",)


def _ledger_projection(
    snapshot: RestartEvidenceSnapshot,
    fields: tuple[str, ...],
) -> tuple[tuple[object, ...], ...]:
    rows = snapshot.state_payload.get("broker_ledgers")
    if not isinstance(rows, list):
        raise ValueError("restart snapshot broker_ledgers must be a list")
    projected: list[tuple[object, ...]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("restart snapshot broker ledger row must be a mapping")
        projected.append(tuple(row.get(field) for field in fields))
    return tuple(projected)


def _sections_equal(
    before: RestartEvidenceSnapshot,
    after: RestartEvidenceSnapshot,
    sections: tuple[str, ...],
) -> bool:
    return all(
        before.state_payload.get(section) == after.state_payload.get(section)
        for section in sections
    )


@dataclass(frozen=True, slots=True)
class RestartEvidenceComparison:
    evidence: RestartScenarioEvidence
    event_count_preserved: bool
    before_state_payload_hash: str
    after_state_payload_hash: str

    @property
    def verified(self) -> bool:
        return self.evidence.verified


def compare_restart_evidence_snapshots(
    *,
    scenario_id: str,
    before: RestartEvidenceSnapshot,
    after: RestartEvidenceSnapshot,
) -> RestartEvidenceComparison:
    """Compare one controlled restart without inventing a successful outcome."""
    if before.deployed_revision != after.deployed_revision:
        raise ValueError("restart snapshots must share one deployed revision")
    if before.scenario != after.scenario:
        raise ValueError("restart snapshots must share one scenario")
    if after.observed_at_utc < before.observed_at_utc:
        raise ValueError("after restart snapshot cannot predate before snapshot")
    if before.synthetic or after.synthetic:
        raise ValueError("synthetic restart snapshots are not admissible")

    before_events = before.state_payload.get("event_count")
    after_events = after.state_payload.get("event_count")
    event_count_preserved = before_events == after_events

    identity_preserved = (
        event_count_preserved
        and _sections_equal(before, after, _IDENTITY_SECTIONS)
    )
    cash_preserved = _ledger_projection(
        before,
        (
            "broker_account_id",
            "cash_available_usd",
            "cash_reserved_usd",
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "fees_accrued_usd",
            "carry_accrued_usd",
            "settled_cash_usd",
            "row_version",
        ),
    ) == _ledger_projection(
        after,
        (
            "broker_account_id",
            "cash_available_usd",
            "cash_reserved_usd",
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "fees_accrued_usd",
            "carry_accrued_usd",
            "settled_cash_usd",
            "row_version",
        ),
    )
    margin_preserved = _ledger_projection(
        before,
        (
            "broker_account_id",
            "margin_used_usd",
            "margin_available_usd",
            "row_version",
        ),
    ) == _ledger_projection(
        after,
        (
            "broker_account_id",
            "margin_used_usd",
            "margin_available_usd",
            "row_version",
        ),
    )
    position_state_preserved = _sections_equal(
        before,
        after,
        _POSITION_SECTIONS,
    )
    idempotency_preserved = _sections_equal(
        before,
        after,
        _IDEMPOTENCY_SECTIONS,
    ) and before.state_payload.get(
        "in_flight_order_intents"
    ) == after.state_payload.get(
        "in_flight_order_intents"
    )
    reconciliation_clean = bool(
        not before.reconciliation_blockers
        and not after.reconciliation_blockers
        and before.state_payload.get("risk_admission_issues") == []
        and after.state_payload.get("risk_admission_issues") == []
    )

    source_ids = tuple(
        dict.fromkeys(
            (*before.source_artifact_ids, *after.source_artifact_ids)
        )
    )
    evidence = RestartScenarioEvidence(
        scenario_id=scenario_id,
        scenario=before.scenario,
        deployed_revision=before.deployed_revision,
        observed_at_utc=after.observed_at_utc,
        identity_preserved=identity_preserved,
        cash_preserved=cash_preserved,
        margin_preserved=margin_preserved,
        position_state_preserved=position_state_preserved,
        idempotency_preserved=idempotency_preserved,
        reconciliation_clean=reconciliation_clean,
        source_artifact_ids=source_ids,
        synthetic=False,
    )
    return RestartEvidenceComparison(
        evidence=evidence,
        event_count_preserved=event_count_preserved,
        before_state_payload_hash=before.state_payload_hash,
        after_state_payload_hash=after.state_payload_hash,
    )
