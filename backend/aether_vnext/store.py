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

from aether_vnext.domain import MarketObservation
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

    def record_market_observation(
        self,
        conn: Connection,
        observation: MarketObservation,
    ) -> None:
        table = self.tables["market_observations"]
        conn.execute(
            table.insert().values(
                observation_id=observation.observation_id,
                asset_id=observation.asset_id,
                venue=observation.venue,
                bid=observation.bid,
                ask=observation.ask,
                last=observation.last,
                mark=observation.mark,
                source=observation.source,
                exchange_ts=observation.exchange_ts,
                received_ts=observation.received_ts,
                age_ms=observation.age_ms,
                spread_abs=observation.spread_abs,
                spread_bps=observation.spread_bps,
                session_state=observation.session_state.value,
                quality_state=observation.quality_state.value,
                fallback_reason=observation.fallback_reason,
                calendar_state=observation.calendar_state.value,
                data_version=observation.data_version,
            )
        )

    def reserve_order_intent(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
        ticket_id: str,
        firm_event_id: str | None,
        asset_id: str,
        route_id: str,
        broker_account_id: str,
        broker: str,
        venue: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str,
        reference_price: float | None,
        expected_fill: float | None,
        idempotency_key: str,
        signal_key: str,
        position_key: str,
        reserve_cash_usd: float,
        reserve_margin_usd: float,
        ready_spread_bps: float | None,
        hard_stop_price: float | None,
        exit_plan_id: str | None,
        submit_timeout_at: datetime | None,
        policy_version: str,
        configuration_hash: str,
        market_observation_id: str,
        created_at_utc: datetime,
        event_id: str,
        actor: str,
        intent_kind: str = "OPEN",
    ) -> dict[str, Any]:
        """Atomically reserve one broker-local ledger and create RESERVED intent.

        Caller owns the SQL transaction. This method never waits for an adapter.
        """
        if qty <= 0:
            raise ValueError("qty must be positive")
        if reserve_cash_usd < 0 or reserve_margin_usd < 0:
            raise ValueError("reservation amounts cannot be negative")

        intents = self.tables["order_intents"]
        ledgers = self.tables["broker_account_ledgers"]

        ledger = conn.execute(
            sa.select(ledgers)
            .where(ledgers.c.broker_account_id == broker_account_id)
            .with_for_update()
        ).mappings().first()
        if ledger is None:
            raise KeyError(f"unknown broker ledger: {broker_account_id}")

        existing = conn.execute(
            sa.select(intents).where(
                intents.c.idempotency_key == idempotency_key
            )
        ).mappings().first()
        if existing is not None:
            return {
                "ok": True,
                "duplicate": True,
                "order_intent_id": existing["order_intent_id"],
                "state": existing["state"],
            }

        cash_available = float(ledger["cash_available_usd"])
        cash_reserved = float(ledger["cash_reserved_usd"])
        margin_used = float(ledger["margin_used_usd"])
        margin_available = float(ledger["margin_available_usd"])
        if cash_available + 1e-9 < reserve_cash_usd:
            return {
                "ok": False,
                "error": "insufficient_capital",
                "broker_account_id": broker_account_id,
            }
        if margin_available + 1e-9 < reserve_margin_usd:
            return {
                "ok": False,
                "error": "insufficient_capital",
                "broker_account_id": broker_account_id,
            }

        conn.execute(
            intents.insert().values(
                order_intent_id=order_intent_id,
                ticket_id=ticket_id,
                firm_event_id=firm_event_id,
                asset_id=asset_id,
                route_id=route_id,
                broker_account_id=broker_account_id,
                broker=broker,
                venue=venue,
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=order_type,
                reference_price=reference_price,
                expected_fill=expected_fill,
                state="RESERVED",
                submitted_at=None,
                acknowledged_at=None,
                filled_at=None,
                filled_qty=0.0,
                avg_fill_price=None,
                reject_code=None,
                slippage_usd=None,
                slippage_bps=None,
                idempotency_key=idempotency_key,
                exit_plan_id=exit_plan_id,
                intent_kind=intent_kind,
                position_key=position_key,
                signal_key=signal_key,
                reserved_cash_usd=reserve_cash_usd,
                reserved_margin_usd=reserve_margin_usd,
                ready_spread_bps=ready_spread_bps,
                hard_stop_price=hard_stop_price,
                submit_timeout_at=submit_timeout_at,
                fill_market_observation_id=None,
                trade_id=None,
                row_version=1,
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                market_observation_id=market_observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=created_at_utc,
            )
        )
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == broker_account_id)
            .values(
                cash_available_usd=cash_available - reserve_cash_usd,
                cash_reserved_usd=cash_reserved + reserve_cash_usd,
                margin_used_usd=margin_used + reserve_margin_usd,
                margin_available_usd=margin_available - reserve_margin_usd,
                row_version=int(ledger["row_version"]) + 1,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="order_intent",
            aggregate_id=order_intent_id,
            prior_state="READY",
            new_state="RESERVED",
            seat="Portfolio",
            reason_code="portfolio.reserve",
            policy_version=policy_version,
            configuration_hash=configuration_hash,
            market_observation_id=market_observation_id,
            actor=actor,
            created_at_utc=created_at_utc,
            payload={
                "broker_account_id": broker_account_id,
                "reserve_cash_usd": reserve_cash_usd,
                "reserve_margin_usd": reserve_margin_usd,
                "idempotency_key": idempotency_key,
                "signal_key": signal_key,
                "position_key": position_key,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "order_intent_id": order_intent_id,
            "state": "RESERVED",
        }

    def mark_order_intent_submitted(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
        submitted_at_utc: datetime,
        acknowledged_at_utc: datetime,
        submit_timeout_at: datetime,
        event_id: str,
        actor: str,
    ) -> dict[str, Any]:
        intents = self.tables["order_intents"]
        row = conn.execute(
            sa.select(intents)
            .where(intents.c.order_intent_id == order_intent_id)
            .with_for_update()
        ).mappings().first()
        if row is None:
            raise KeyError(f"unknown order intent: {order_intent_id}")
        if row["state"] in {
            "SUBMITTED",
            "FILLED",
            "REJECTED",
            "CANCELLED",
            "CANCELLED_STALE",
        }:
            return {"ok": True, "duplicate": True, "state": row["state"]}
        if row["state"] != "RESERVED":
            return {"ok": False, "error": "illegal_state", "state": row["state"]}

        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == order_intent_id)
            .values(
                state="SUBMITTED",
                submitted_at=submitted_at_utc,
                acknowledged_at=acknowledged_at_utc,
                submit_timeout_at=submit_timeout_at,
                row_version=int(row["row_version"]) + 1,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="order_intent",
            aggregate_id=order_intent_id,
            prior_state="RESERVED",
            new_state="SUBMITTED",
            seat="Portfolio",
            reason_code="execution.submitted",
            policy_version=row["policy_version"],
            configuration_hash=row["configuration_hash"],
            market_observation_id=row["market_observation_id"],
            actor=actor,
            created_at_utc=submitted_at_utc,
            payload={"submit_timeout_at": submit_timeout_at.isoformat()},
        )
        return {"ok": True, "duplicate": False, "state": "SUBMITTED"}

    def release_order_reservation(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
        terminal_state: str,
        reject_code: str,
        at_utc: datetime,
        event_id: str,
        actor: str,
        fill_market_observation_id: str | None = None,
    ) -> dict[str, Any]:
        if terminal_state not in {"REJECTED", "CANCELLED", "CANCELLED_STALE"}:
            raise ValueError("terminal_state must release a zero-fill reservation")

        intents = self.tables["order_intents"]
        ledgers = self.tables["broker_account_ledgers"]

        intent = conn.execute(
            sa.select(intents)
            .where(intents.c.order_intent_id == order_intent_id)
            .with_for_update()
        ).mappings().first()
        if intent is None:
            raise KeyError(f"unknown order intent: {order_intent_id}")
        if intent["state"] in {"FILLED", "REJECTED", "CANCELLED", "CANCELLED_STALE"}:
            return {"ok": True, "duplicate": True, "state": intent["state"]}

        ledger = conn.execute(
            sa.select(ledgers)
            .where(
                ledgers.c.broker_account_id == intent["broker_account_id"]
            )
            .with_for_update()
        ).mappings().one()

        reserve_cash = float(intent["reserved_cash_usd"])
        reserve_margin = float(intent["reserved_margin_usd"])
        cash_reserved = float(ledger["cash_reserved_usd"])
        margin_used = float(ledger["margin_used_usd"])
        if cash_reserved + 1e-9 < reserve_cash:
            raise RuntimeError("cash reservation drift")
        if margin_used + 1e-9 < reserve_margin:
            raise RuntimeError("margin reservation drift")

        conn.execute(
            ledgers.update()
            .where(
                ledgers.c.broker_account_id == intent["broker_account_id"]
            )
            .values(
                cash_available_usd=float(ledger["cash_available_usd"]) + reserve_cash,
                cash_reserved_usd=cash_reserved - reserve_cash,
                margin_used_usd=margin_used - reserve_margin,
                margin_available_usd=float(ledger["margin_available_usd"]) + reserve_margin,
                row_version=int(ledger["row_version"]) + 1,
            )
        )
        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == order_intent_id)
            .values(
                state=terminal_state,
                reject_code=reject_code,
                fill_market_observation_id=fill_market_observation_id,
                row_version=int(intent["row_version"]) + 1,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="order_intent",
            aggregate_id=order_intent_id,
            prior_state=intent["state"],
            new_state=terminal_state,
            seat="Portfolio",
            reason_code=reject_code,
            policy_version=intent["policy_version"],
            configuration_hash=intent["configuration_hash"],
            market_observation_id=(
                fill_market_observation_id or intent["market_observation_id"]
            ),
            actor=actor,
            created_at_utc=at_utc,
            payload={
                "released_cash_usd": reserve_cash,
                "released_margin_usd": reserve_margin,
            },
        )
        return {"ok": True, "duplicate": False, "state": terminal_state}

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
