"""Read-only restart-state evidence snapshots for AETHER Phase 17."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Connection

from aether_vnext.restart import load_restart_snapshot
from aether_vnext.runtime_book_health import runtime_book_blockers
from aether_vnext.store import VNextStore, canonical_payload_hash


RESTART_EVIDENCE_SCENARIOS = frozenset(
    {"mid_ticket", "mid_order", "open_trade"}
)


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _row_projection(
    rows: tuple[dict[str, Any], ...],
    fields: tuple[str, ...],
    *,
    sort_fields: tuple[str, ...],
) -> list[dict[str, object]]:
    projected = [
        {field: row.get(field) for field in fields}
        for row in rows
    ]
    return sorted(
        projected,
        key=lambda row: tuple(str(row.get(field)) for field in sort_fields),
    )


@dataclass(frozen=True, slots=True)
class RestartEvidenceSnapshot:
    snapshot_id: str
    deployed_revision: str
    scenario: str
    observed_at_utc: datetime
    state_payload: dict[str, object]
    state_payload_hash: str
    reconciliation_blockers: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "deployed_revision"):
            _canonical_text(name, getattr(self, name))
        if self.scenario not in RESTART_EVIDENCE_SCENARIOS:
            raise ValueError("unsupported restart evidence scenario")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if not self.source_artifact_ids:
            raise ValueError("source_artifact_ids must not be empty")
        for source_id in self.source_artifact_ids:
            _canonical_text("source_artifact_id", source_id)
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("source_artifact_ids cannot contain duplicates")
        expected_hash = canonical_payload_hash(self.state_payload)
        if self.state_payload_hash != expected_hash:
            raise ValueError("restart state payload hash mismatch")
        if self.synthetic is not False:
            raise ValueError("synthetic restart snapshot evidence is not admissible")


def collect_restart_evidence_snapshot(
    conn: Connection,
    *,
    store: VNextStore,
    snapshot_id: str,
    deployed_revision: str,
    scenario: str,
    observed_at_utc: datetime,
    source_artifact_ids: tuple[str, ...],
) -> RestartEvidenceSnapshot:
    """Capture durable restart state without mutating, reconciling, or reseeding."""
    if scenario not in RESTART_EVIDENCE_SCENARIOS:
        raise ValueError("unsupported restart evidence scenario")
    snapshot = load_restart_snapshot(conn, store=store)

    payload: dict[str, object] = {
        "event_count": snapshot.event_count,
        "broker_ledgers": _row_projection(
            snapshot.broker_ledgers,
            (
                "broker_account_id",
                "cash_available_usd",
                "cash_reserved_usd",
                "margin_used_usd",
                "margin_available_usd",
                "realized_pnl_usd",
                "unrealized_pnl_usd",
                "fees_accrued_usd",
                "carry_accrued_usd",
                "settled_cash_usd",
                "reconciliation_state",
                "row_version",
            ),
            sort_fields=("broker_account_id",),
        ),
        "in_flight_setups": _row_projection(
            snapshot.in_flight_setups,
            (
                "setup_id",
                "firm_event_id",
                "asset_id",
                "route_id",
                "state",
                "side",
                "horizon",
                "policy_version",
                "configuration_hash",
            ),
            sort_fields=("setup_id",),
        ),
        "in_flight_tickets": _row_projection(
            snapshot.in_flight_tickets,
            (
                "ticket_id",
                "firm_event_id",
                "setup_id",
                "asset_id",
                "route_id",
                "state",
                "side",
                "horizon",
                "quantity",
                "policy_version",
                "configuration_hash",
            ),
            sort_fields=("ticket_id",),
        ),
        "in_flight_order_intents": _row_projection(
            snapshot.in_flight_order_intents,
            (
                "order_intent_id",
                "ticket_id",
                "firm_event_id",
                "asset_id",
                "route_id",
                "intent_kind",
                "state",
                "position_key",
                "signal_key",
                "requested_qty",
                "idempotency_key",
                "policy_version",
                "configuration_hash",
            ),
            sort_fields=("order_intent_id",),
        ),
        "active_positions": _row_projection(
            snapshot.active_positions,
            (
                "position_key",
                "trade_id",
                "asset_id",
                "horizon",
                "side",
                "quantity",
                "row_version",
            ),
            sort_fields=("position_key",),
        ),
        "open_trade_records": _row_projection(
            snapshot.open_trade_records,
            (
                "trade_id",
                "order_intent_id",
                "ticket_id",
                "setup_id",
                "firm_event_id",
                "asset_id",
                "route_id",
                "position_key",
                "side",
                "quantity",
                "avg_entry_price",
                "initial_stop_risk_usd",
                "policy_version",
                "configuration_hash",
            ),
            sort_fields=("trade_id",),
        ),
        "consumed_signals": _row_projection(
            snapshot.consumed_signals,
            (
                "signal_key",
                "trade_id",
                "asset_id",
                "route_id",
            ),
            sort_fields=("signal_key",),
        ),
        "mutation_idempotency": _row_projection(
            snapshot.mutation_idempotency,
            (
                "idempotency_key",
                "mutation_type",
                "aggregate_type",
                "aggregate_id",
                "result_payload_hash",
            ),
            sort_fields=("idempotency_key",),
        ),
        "risk_admission_issues": list(snapshot.risk_admission_issues),
    }

    blockers = runtime_book_blockers(
        conn,
        store=store,
        as_of_utc=observed_at_utc,
    )
    return RestartEvidenceSnapshot(
        snapshot_id=snapshot_id,
        deployed_revision=deployed_revision,
        scenario=scenario,
        observed_at_utc=observed_at_utc,
        state_payload=payload,
        state_payload_hash=canonical_payload_hash(payload),
        reconciliation_blockers=tuple(blockers),
        source_artifact_ids=source_artifact_ids,
        synthetic=False,
    )
