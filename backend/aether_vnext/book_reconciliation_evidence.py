"""Read-only Phase-17 canonical book reconciliation evidence collection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.full_swap_evidence_readiness import (
    BookReconciliationEvidence,
)
from aether_vnext.store import SEED_LEDGER_CASH_USD, VNextStore


_LEDGER_NONNEGATIVE_FIELDS = (
    "cash_available_usd",
    "cash_reserved_usd",
    "margin_used_usd",
    "margin_available_usd",
)


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def active_position_identity_issues(
    *,
    active_rows: tuple[Mapping[str, Any], ...],
    trade_rows: tuple[Mapping[str, Any], ...],
    closed_trade_ids: frozenset[str],
) -> tuple[str, ...]:
    """Return deterministic identity defects without repairing persisted state."""
    trades = {str(row["trade_id"]): row for row in trade_rows}
    issues: list[str] = []

    for active in sorted(
        active_rows,
        key=lambda row: (str(row["position_key"]), str(row["trade_id"])),
    ):
        trade_id = str(active["trade_id"])
        position_key = str(active["position_key"])
        trade = trades.get(trade_id)
        if trade is None:
            issues.append(f"active_position_missing_trade:{position_key}:{trade_id}")
            continue
        if trade_id in closed_trade_ids:
            issues.append(f"active_position_references_closed_trade:{position_key}:{trade_id}")
        if str(trade["position_key"]) != position_key:
            issues.append(f"active_position_position_key_mismatch:{position_key}:{trade_id}")
        if str(trade["asset_id"]) != str(active["asset_id"]):
            issues.append(f"active_position_asset_mismatch:{position_key}:{trade_id}")
        if str(trade["side"]) != str(active["side"]):
            issues.append(f"active_position_side_mismatch:{position_key}:{trade_id}")
        if abs(float(trade["quantity"]) - float(active["quantity"])) > 1e-12:
            issues.append(f"active_position_quantity_mismatch:{position_key}:{trade_id}")

    return tuple(issues)


def broker_ledger_issues(
    rows: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    """Use frozen sleeve identities and durable reconciliation state only."""
    expected = set(SEED_LEDGER_CASH_USD)
    actual = {str(row["broker_account_id"]) for row in rows}
    issues: list[str] = []

    for broker_id in sorted(expected - actual):
        issues.append(f"broker_ledger_missing:{broker_id}")
    for broker_id in sorted(actual - expected):
        issues.append(f"broker_ledger_unexpected:{broker_id}")

    for row in sorted(rows, key=lambda item: str(item["broker_account_id"])):
        broker_id = str(row["broker_account_id"])
        if str(row["reconciliation_state"]) != "clean":
            issues.append(f"broker_ledger_reconciliation_not_clean:{broker_id}")
        if int(row["row_version"]) < 1:
            issues.append(f"broker_ledger_row_version_invalid:{broker_id}")
        for field in _LEDGER_NONNEGATIVE_FIELDS:
            value = float(row[field])
            if not math.isfinite(value) or value < 0:
                issues.append(f"broker_ledger_invalid_{field}:{broker_id}")

    return tuple(issues)


@dataclass(frozen=True, slots=True)
class CollectedBookReconciliationEvidence:
    evidence: BookReconciliationEvidence
    active_position_identity_issues: tuple[str, ...]
    broker_ledger_issues: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.evidence.verified


def collect_book_reconciliation_evidence(
    conn: Connection,
    *,
    store: VNextStore,
    evidence_id: str,
    deployed_revision: str,
    observed_at_utc: datetime,
    source_artifact_ids: tuple[str, ...],
) -> CollectedBookReconciliationEvidence:
    """Collect canonical, non-synthetic evidence using SELECT-only book reads."""
    _canonical_text("evidence_id", evidence_id)
    _canonical_text("deployed_revision", deployed_revision)
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")

    risk_issues = store.risk_admission_reconciliation_issues(conn)
    stale_ids = store.stale_order_intent_ids(conn, at_utc=observed_at_utc)

    active_rows = tuple(
        dict(row)
        for row in conn.execute(
            sa.select(store.tables["active_positions"]).order_by(
                store.tables["active_positions"].c.position_key.asc()
            )
        ).mappings()
    )
    trade_rows = tuple(
        dict(row)
        for row in conn.execute(
            sa.select(store.tables["open_trades"]).order_by(
                store.tables["open_trades"].c.trade_id.asc()
            )
        ).mappings()
    )
    closed_trade_ids = frozenset(
        str(row[0])
        for row in conn.execute(
            sa.select(store.tables["closed_trades"].c.trade_id)
        )
    )
    identity_issues = active_position_identity_issues(
        active_rows=active_rows,
        trade_rows=trade_rows,
        closed_trade_ids=closed_trade_ids,
    )

    ledger_rows = tuple(store.ledger_rows(conn))
    ledger_issues = broker_ledger_issues(ledger_rows)

    evidence = BookReconciliationEvidence(
        evidence_id=evidence_id,
        deployed_revision=deployed_revision,
        observed_at_utc=observed_at_utc,
        risk_admission_issues=tuple(risk_issues),
        stale_order_intent_ids=tuple(stale_ids),
        active_position_trade_identity_consistent=not identity_issues,
        broker_ledger_balanced=not ledger_issues,
        source_artifact_ids=source_artifact_ids,
        synthetic=False,
    )
    return CollectedBookReconciliationEvidence(
        evidence=evidence,
        active_position_identity_issues=identity_issues,
        broker_ledger_issues=ledger_issues,
    )
