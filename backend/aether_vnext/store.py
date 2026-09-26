"""AETHER vNext persistence primitives.

These functions operate on the vNext book-of-record schema only. They do not import
legacy persistence and they deliberately expose DB uniqueness as part of Firm safety.

Application restart must never seed capital. `provision_seed_ledgers_once` is a
provisioning/migration primitive, not a boot hook.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.schema import build_metadata


SEED_LEDGER_CASH_USD: Mapping[str, float] = {
    "kraken_paper": 4000.0,
    "tastyfx_paper": 2000.0,
    "ninja_paper": 2000.0,
    "ibkr_paper": 2000.0,
}


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class VNextStore:
    def __init__(self, *, schema: str | None = "aether_vnext") -> None:
        self.schema = schema
        self.metadata = build_metadata(schema=schema)
        self.tables = {
            table.name: table
            for table in self.metadata.tables.values()
        }

    def create_all_for_test(self, conn: Connection) -> None:
        """Test helper only. Production schema changes go through Alembic."""
        self.metadata.create_all(bind=conn, checkfirst=True)

    def provision_seed_ledgers_once(self, conn: Connection) -> bool:
        """Insert the frozen $10k paper sleeves only if no ledger rows exist.

        Returns True when provisioning occurred. Returns False on every later call,
        even if balances changed, which prevents restart from minting/reseeding cash.
        """
        ledgers = self.tables["broker_account_ledgers"]
        existing = conn.execute(
            sa.select(sa.func.count()).select_from(ledgers)
        ).scalar_one()
        if int(existing) != 0:
            return False
        conn.execute(
            ledgers.insert(),
            [
                {
                    "broker_account_id": ledger_id,
                    "cash_available_usd": cash,
                    "cash_reserved_usd": 0.0,
                    "margin_used_usd": 0.0,
                    "margin_available_usd": cash,
                    "realized_pnl_usd": 0.0,
                    "unrealized_pnl_usd": 0.0,
                    "fees_accrued_usd": 0.0,
                    "settled_cash_usd": cash,
                    "reconciliation_state": "clean",
                    "row_version": 1,
                }
                for ledger_id, cash in SEED_LEDGER_CASH_USD.items()
            ],
        )
        return True

    def append_event(
        self,
        conn: Connection,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        prior_state: str | None,
        new_state: str,
        seat: str,
        reason_code: str,
        policy_version: str,
        configuration_hash: str,
        market_observation_id: str | None,
        actor: str,
        created_at_utc: datetime,
        payload: Mapping[str, Any],
    ) -> str:
        events = self.tables["event_ledger"]
        payload_dict = dict(payload)
        payload_hash = canonical_payload_hash(payload_dict)
        conn.execute(
            events.insert().values(
                event_id=event_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                prior_state=prior_state,
                new_state=new_state,
                seat=seat,
                reason_code=reason_code,
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                market_observation_id=market_observation_id,
                actor=actor,
                created_at_utc=created_at_utc,
                payload_hash=payload_hash,
                payload=payload_dict,
            )
        )
        return payload_hash

    def consume_signal(
        self,
        conn: Connection,
        *,
        signal_key: str,
        order_intent_id: str,
        trade_id: str,
        consumed_at_utc: datetime,
    ) -> None:
        table = self.tables["signal_consumptions"]
        conn.execute(
            table.insert().values(
                signal_key=signal_key,
                order_intent_id=order_intent_id,
                trade_id=trade_id,
                consumed_at_utc=consumed_at_utc,
            )
        )

    def claim_active_position(
        self,
        conn: Connection,
        *,
        position_key: str,
        trade_id: str,
        asset_id: str,
        horizon: str,
        side: str,
        quantity: float,
        updated_at_utc: datetime,
    ) -> None:
        table = self.tables["active_positions"]
        conn.execute(
            table.insert().values(
                position_key=position_key,
                trade_id=trade_id,
                asset_id=asset_id,
                horizon=horizon,
                side=side,
                quantity=quantity,
                row_version=1,
                updated_at_utc=updated_at_utc,
            )
        )

    def release_active_position(
        self,
        conn: Connection,
        *,
        position_key: str,
        trade_id: str,
    ) -> int:
        table = self.tables["active_positions"]
        result = conn.execute(
            table.delete().where(
                sa.and_(
                    table.c.position_key == position_key,
                    table.c.trade_id == trade_id,
                )
            )
        )
        return int(result.rowcount or 0)

    def record_mutation_idempotency(
        self,
        conn: Connection,
        *,
        idempotency_key: str,
        mutation_type: str,
        aggregate_type: str,
        aggregate_id: str,
        created_at_utc: datetime,
        result_payload_hash: str | None = None,
    ) -> None:
        table = self.tables["mutation_idempotency"]
        conn.execute(
            table.insert().values(
                idempotency_key=idempotency_key,
                mutation_type=mutation_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                result_payload_hash=result_payload_hash,
                created_at_utc=created_at_utc,
            )
        )

    def ledger_rows(self, conn: Connection) -> list[dict[str, Any]]:
        table = self.tables["broker_account_ledgers"]
        rows = conn.execute(
            sa.select(table).order_by(table.c.broker_account_id)
        ).mappings()
        return [dict(row) for row in rows]

    def event_rows(self, conn: Connection) -> list[dict[str, Any]]:
        table = self.tables["event_ledger"]
        rows = conn.execute(
            sa.select(table).order_by(table.c.created_at_utc, table.c.event_id)
        ).mappings()
        return [dict(row) for row in rows]
