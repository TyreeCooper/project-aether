"""AETHER vNext persistence primitives.

These functions operate on the vNext book-of-record schema only. They do not import
legacy persistence and they deliberately expose DB uniqueness as part of Firm safety.

Application restart must never seed capital. `provision_seed_ledgers_once` is a
provisioning/migration primitive, not a boot hook.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import (
    Lineage,
    MarketObservation,
    OrderIntent,
    OrderIntentState,
)
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


def _stored_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _horizon_from_position_key(value: str) -> str:
    parts = str(value).split(":")
    if len(parts) != 2 or not parts[1]:
        raise ValueError("position_key must be asset:horizon")
    return parts[1]


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
                    "inventory_qty": 0.0,
                    "inventory_avg": None,
                    "realized_pnl_usd": 0.0,
                    "unrealized_pnl_usd": 0.0,
                    "fees_accrued_usd": 0.0,
                    "carry_accrued_usd": 0.0,
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

    def load_order_intent(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
    ) -> OrderIntent | None:
        table = self.tables["order_intents"]
        row = conn.execute(
            sa.select(table).where(
                table.c.order_intent_id == order_intent_id
            )
        ).mappings().first()
        if row is None:
            return None
        return OrderIntent(
            order_intent_id=row["order_intent_id"],
            lineage=Lineage(
                asset_id=row["asset_id"],
                route_id=row["route_id"],
                policy_version=row["policy_version"],
                configuration_hash=row["configuration_hash"],
                market_observation_id=row["market_observation_id"],
                created_at_utc=_stored_utc(row["created_at_utc"]),
                firm_event_id=row["firm_event_id"],
                ticket_id=row["ticket_id"],
                order_intent_id=row["order_intent_id"],
                trade_id=row["trade_id"],
                first_killed_by=row["first_killed_by"],
                first_kill_reason=row["first_kill_reason"],
            ),
            broker=row["broker"],
            venue=row["venue"],
            symbol=row["symbol"],
            side=row["side"],
            qty=float(row["qty"]),
            order_type=row["order_type"],
            reference_price=row["reference_price"],
            expected_fill=row["expected_fill"],
            state=OrderIntentState(row["state"]),
            submitted_at=_stored_utc(row["submitted_at"]),
            acknowledged_at=_stored_utc(row["acknowledged_at"]),
            filled_at=_stored_utc(row["filled_at"]),
            filled_qty=float(row["filled_qty"]),
            avg_fill_price=row["avg_fill_price"],
            reject_code=row["reject_code"],
            slippage_usd=row["slippage_usd"],
            slippage_bps=row["slippage_bps"],
            idempotency_key=row["idempotency_key"],
            broker_account_id=row["broker_account_id"],
            intent_kind=row["intent_kind"],
            exit_reason=row["exit_reason"],
            position_key=row["position_key"],
            signal_key=row["signal_key"],
            reserved_cash_usd=float(row["reserved_cash_usd"]),
            reserved_margin_usd=float(row["reserved_margin_usd"]),
            ready_spread_bps=row["ready_spread_bps"],
            hard_stop_price=row["hard_stop_price"],
            submit_timeout_at=_stored_utc(row["submit_timeout_at"]),
            fill_market_observation_id=row["fill_market_observation_id"],
            trade_id=row["trade_id"],
            row_version=int(row["row_version"]),
        )

    def reject_ticket_pre_reserve(
        self,
        conn: Connection,
        *,
        ticket_id: str,
        reason_code: str,
        at_utc: datetime,
        event_id: str,
        actor: str,
        market_observation_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Portfolio Phase-A rejection with no OrderIntent/reserve."""
        tickets = self.tables["tickets"]
        row = conn.execute(
            sa.select(tickets)
            .where(tickets.c.ticket_id == ticket_id)
            .with_for_update()
        ).mappings().first()
        if row is None:
            raise KeyError(f"unknown ticket: {ticket_id}")
        if row["state"] == "REJECTED":
            return {
                "ok": True,
                "duplicate": True,
                "state": "REJECTED",
                "reject_code": row["reject_code"],
            }
        if row["state"] != "READY":
            return {
                "ok": False,
                "error": "ticket_not_ready",
                "state": row["state"],
            }

        observation_id = (
            market_observation_id or row["market_observation_id"]
        )
        conn.execute(
            tickets.update()
            .where(tickets.c.ticket_id == ticket_id)
            .values(
                state="REJECTED",
                reject_code=reason_code,
                first_killed_by="Portfolio",
                first_kill_reason=reason_code,
                market_observation_id=observation_id,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="ticket",
            aggregate_id=ticket_id,
            prior_state="READY",
            new_state="REJECTED",
            seat="Portfolio",
            reason_code=reason_code,
            policy_version=row["policy_version"],
            configuration_hash=row["configuration_hash"],
            market_observation_id=observation_id,
            actor=actor,
            created_at_utc=at_utc,
            payload={
                "first_killed_by": "Portfolio",
                "first_kill_reason": reason_code,
                "order_intent_created": False,
                "reservation_created": False,
            },
        )
        return {
            "ok": False,
            "duplicate": False,
            "error": reason_code,
            "state": "REJECTED",
            "reject_code": reason_code,
        }

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
        if reserve_cash_usd + 1e-9 < reserve_margin_usd:
            raise ValueError(
                "reserve_cash_usd must include at least the locked margin"
            )

        if submit_timeout_at is None:
            submit_timeout_at = created_at_utc + timedelta(milliseconds=15_000)

        intents = self.tables["order_intents"]
        ledgers = self.tables["broker_account_ledgers"]
        signals = self.tables["signal_consumptions"]
        positions = self.tables["active_positions"]
        tickets = self.tables["tickets"]

        # Idempotent retry wins before re-evaluating mutable current state.
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

        ticket = conn.execute(
            sa.select(tickets)
            .where(tickets.c.ticket_id == ticket_id)
            .with_for_update()
        ).mappings().first()
        if ticket is None:
            return {
                "ok": False,
                "error": "unknown_ticket",
                "ticket_id": ticket_id,
            }
        if ticket["state"] != "READY":
            return {
                "ok": False,
                "error": "ticket_not_ready",
                "state": ticket["state"],
            }
        if (
            ticket["configuration_hash"] != configuration_hash
            or ticket["policy_version"] != policy_version
        ):
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="configuration_mismatch",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        if ticket["exit_plan_id"] is None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="exit_plan_missing",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        if (
            ticket["asset_id"] != asset_id
            or ticket["route_id"] != route_id
            or ticket["signal_key"] != signal_key
            or ticket["side"] != side
            or ticket["exit_plan_id"] != exit_plan_id
            or abs(float(ticket["quantity"] or 0.0) - float(qty)) > 1e-12
        ):
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="ticket_contract_mismatch",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        ledger = conn.execute(
            sa.select(ledgers)
            .where(ledgers.c.broker_account_id == broker_account_id)
            .with_for_update()
        ).mappings().first()
        if ledger is None:
            raise KeyError(f"unknown broker ledger: {broker_account_id}")

        consumed = conn.execute(
            sa.select(signals.c.trade_id).where(
                signals.c.signal_key == signal_key
            )
        ).first()
        if consumed is not None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="signal_consumed",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        active = conn.execute(
            sa.select(positions.c.trade_id).where(
                positions.c.position_key == position_key
            )
        ).first()
        if active is not None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="duplicate_position_key",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        cash_available = float(ledger["cash_available_usd"])
        cash_reserved = float(ledger["cash_reserved_usd"])
        margin_used = float(ledger["margin_used_usd"])
        margin_available = float(ledger["margin_available_usd"])
        if (
            cash_available + 1e-9 < reserve_cash_usd
            or margin_available + 1e-9 < reserve_margin_usd
        ):
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="insufficient_capital",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

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
        submit_timeout_at: datetime | None,
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

        durable_timeout = row["submit_timeout_at"]
        if durable_timeout is None:
            durable_timeout = (
                submit_timeout_at
                or submitted_at_utc + timedelta(milliseconds=15_000)
            )

        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == order_intent_id)
            .values(
                state="SUBMITTED",
                submitted_at=submitted_at_utc,
                acknowledged_at=acknowledged_at_utc,
                submit_timeout_at=durable_timeout,
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
            payload={"submit_timeout_at": durable_timeout.isoformat()},
        )
        return {"ok": True, "duplicate": False, "state": "SUBMITTED"}

    def finalize_filled_open(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
        trade_id: str,
        setup_id: str,
        exit_plan_id: str,
        fill_market_observation_id: str,
        filled_at_utc: datetime,
        filled_qty: float,
        avg_fill_price: float,
        slippage_usd: float,
        slippage_bps: float,
        initial_stop_risk_usd: float,
        management_telemetry: Mapping[str, Any],
        event_id: str,
        actor: str,
    ) -> dict[str, Any]:
        """Atomically convert a SUBMITTED all-or-none intent into one OPEN trade.

        The broker reservation remains locked while the trade is OPEN. Signal
        consumption, active-position occupancy, OpenTrade creation, intent fill
        state, lineage, and EventLedger are committed together.
        """
        if filled_qty <= 0 or avg_fill_price <= 0:
            raise ValueError("filled quantity and price must be positive")
        if initial_stop_risk_usd < 0:
            raise ValueError("initial_stop_risk_usd cannot be negative")

        intents = self.tables["order_intents"]
        trades = self.tables["open_trades"]
        positions = self.tables["active_positions"]
        signals = self.tables["signal_consumptions"]
        lineage = self.tables["decision_lineage"]
        exit_plans = self.tables["exit_plans"]

        intent = conn.execute(
            sa.select(intents)
            .where(intents.c.order_intent_id == order_intent_id)
            .with_for_update()
        ).mappings().first()
        if intent is None:
            raise KeyError(f"unknown order intent: {order_intent_id}")

        if intent["state"] == "FILLED":
            return {
                "ok": True,
                "duplicate": True,
                "state": "FILLED",
                "trade_id": intent["trade_id"],
            }
        if intent["state"] in {"REJECTED", "CANCELLED", "CANCELLED_STALE"}:
            return {
                "ok": False,
                "duplicate": True,
                "error": "terminal_state_wins",
                "state": intent["state"],
            }
        if intent["state"] != "SUBMITTED":
            return {
                "ok": False,
                "error": "illegal_state",
                "state": intent["state"],
            }
        if abs(float(filled_qty) - float(intent["qty"])) > 1e-12:
            return {
                "ok": False,
                "error": "partial_fill_disabled",
                "state": intent["state"],
            }

        position_key_value = str(intent["position_key"] or "")
        signal_key_value = str(intent["signal_key"] or "")
        if not position_key_value:
            raise ValueError("position_key required before OPEN")
        if not signal_key_value:
            raise ValueError("signal_key required before OPEN")

        existing_position = conn.execute(
            sa.select(positions.c.trade_id).where(
                positions.c.position_key == position_key_value
            )
        ).first()
        if existing_position is not None:
            return {
                "ok": False,
                "error": "duplicate_position_key",
                "state": intent["state"],
            }

        existing_signal = conn.execute(
            sa.select(signals.c.trade_id).where(
                signals.c.signal_key == signal_key_value
            )
        ).first()
        if existing_signal is not None:
            return {
                "ok": False,
                "error": "signal_consumed",
                "state": intent["state"],
            }

        plan = conn.execute(
            sa.select(exit_plans).where(
                exit_plans.c.exit_plan_id == exit_plan_id
            )
        ).mappings().first()
        if plan is None:
            return {
                "ok": False,
                "error": "exit_plan_missing",
                "state": intent["state"],
            }
        if intent["exit_plan_id"] not in {None, exit_plan_id}:
            return {
                "ok": False,
                "error": "ticket_contract_mismatch",
                "state": intent["state"],
            }

        exit_plan_payload = {
            "exit_plan_id": plan["exit_plan_id"],
            "version": plan["version"],
            "hard_stop_price": plan["hard_stop_price"],
            "structure_rule_id": plan["structure_rule_id"],
            "time_stop_deadline_utc": (
                _stored_utc(plan["time_stop_deadline_utc"]).isoformat()
                if plan["time_stop_deadline_utc"] is not None
                else None
            ),
            "trailing_policy": dict(plan["trailing_policy"]),
            "profit_take_policy": dict(plan["profit_take_policy"]),
            "session_close_policy": plan["session_close_policy"],
            "stale_mark_policy": plan["stale_mark_policy"],
            "governor_halt_behavior": plan["governor_halt_behavior"],
            "created_from_playbook_version": plan[
                "created_from_playbook_version"
            ],
            "payload_hash": plan["payload_hash"],
        }

        conn.execute(
            trades.insert().values(
                trade_id=trade_id,
                order_intent_id=order_intent_id,
                ticket_id=intent["ticket_id"],
                setup_id=setup_id,
                exit_plan_id=exit_plan_id,
                firm_event_id=intent["firm_event_id"],
                asset_id=intent["asset_id"],
                route_id=intent["route_id"],
                position_key=position_key_value,
                side=intent["side"],
                quantity=filled_qty,
                avg_entry_price=avg_fill_price,
                initial_stop_risk_usd=initial_stop_risk_usd,
                exit_plan_version=plan["version"],
                exit_plan_payload=exit_plan_payload,
                management_telemetry=dict(management_telemetry),
                policy_version=intent["policy_version"],
                configuration_hash=intent["configuration_hash"],
                market_observation_id=fill_market_observation_id,
                opened_at_utc=filled_at_utc,
            )
        )
        conn.execute(
            positions.insert().values(
                position_key=position_key_value,
                trade_id=trade_id,
                asset_id=intent["asset_id"],
                horizon=_horizon_from_position_key(position_key_value),
                side=intent["side"],
                quantity=filled_qty,
                row_version=1,
                updated_at_utc=filled_at_utc,
            )
        )
        conn.execute(
            signals.insert().values(
                signal_key=signal_key_value,
                order_intent_id=order_intent_id,
                trade_id=trade_id,
                consumed_at_utc=filled_at_utc,
            )
        )
        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == order_intent_id)
            .values(
                state="FILLED",
                filled_at=filled_at_utc,
                filled_qty=filled_qty,
                avg_fill_price=avg_fill_price,
                reject_code=None,
                slippage_usd=slippage_usd,
                slippage_bps=slippage_bps,
                fill_market_observation_id=fill_market_observation_id,
                trade_id=trade_id,
                exit_plan_id=exit_plan_id,
                row_version=int(intent["row_version"]) + 1,
            )
        )

        firm_event_id = intent["firm_event_id"]
        if firm_event_id:
            conn.execute(
                lineage.update()
                .where(lineage.c.firm_event_id == firm_event_id)
                .values(
                    setup_id=setup_id,
                    ticket_id=intent["ticket_id"],
                    order_intent_id=order_intent_id,
                    trade_id=trade_id,
                    market_observation_id=fill_market_observation_id,
                    row_version=lineage.c.row_version + 1,
                )
            )

        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="trade",
            aggregate_id=trade_id,
            prior_state="SUBMITTED",
            new_state="OPEN",
            seat="Portfolio",
            reason_code="execution.filled",
            policy_version=intent["policy_version"],
            configuration_hash=intent["configuration_hash"],
            market_observation_id=fill_market_observation_id,
            actor=actor,
            created_at_utc=filled_at_utc,
            payload={
                "order_intent_id": order_intent_id,
                "position_key": position_key_value,
                "signal_key": signal_key_value,
                "filled_qty": filled_qty,
                "avg_fill_price": avg_fill_price,
                "reserved_cash_usd": float(intent["reserved_cash_usd"]),
                "reserved_margin_usd": float(intent["reserved_margin_usd"]),
                "reservation_retained_while_open": True,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "state": "FILLED",
            "trade_id": trade_id,
            "position_key": position_key_value,
            "signal_key": signal_key_value,
        }

    def request_flatten(
        self,
        conn: Connection,
        *,
        trade_id: str,
        exit_reason: str,
        market_observation_id: str,
        at_utc: datetime,
        event_id: str,
        actor: str = "Exit",
    ) -> dict[str, Any]:
        """Record Exit's FLATTEN_REQUEST without touching cash or position state."""
        if not str(exit_reason).strip():
            raise ValueError("exit_reason is required")
        trades = self.tables["open_trades"]
        closed = self.tables["closed_trades"]
        positions = self.tables["active_positions"]

        if conn.execute(
            sa.select(closed.c.trade_id).where(closed.c.trade_id == trade_id)
        ).first() is not None:
            return {"ok": True, "duplicate": True, "state": "FLAT"}

        trade = conn.execute(
            sa.select(trades).where(trades.c.trade_id == trade_id)
        ).mappings().first()
        if trade is None:
            return {"ok": False, "error": "trade_not_open"}

        active = conn.execute(
            sa.select(positions.c.trade_id).where(
                positions.c.position_key == trade["position_key"]
            )
        ).first()
        if active is None or str(active[0]) != trade_id:
            return {"ok": False, "error": "trade_not_open"}

        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="trade",
            aggregate_id=trade_id,
            prior_state="OPEN",
            new_state="FLATTEN_REQUEST",
            seat="Exit",
            reason_code=str(exit_reason),
            policy_version=trade["policy_version"],
            configuration_hash=trade["configuration_hash"],
            market_observation_id=market_observation_id,
            actor=actor,
            created_at_utc=at_utc,
            payload={
                "trade_id": trade_id,
                "position_key": trade["position_key"],
                "exit_reason": str(exit_reason),
                "cash_touched": False,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "state": "FLATTEN_REQUEST",
        }

    def reserve_flatten_intent(
        self,
        conn: Connection,
        *,
        order_intent_id: str,
        trade_id: str,
        idempotency_key: str,
        exit_reason: str,
        market_observation_id: str,
        reference_price: float | None,
        ready_spread_bps: float | None,
        created_at_utc: datetime,
        event_id: str,
        actor: str = "Portfolio",
    ) -> dict[str, Any]:
        """Phase A for CLOSE: create RESERVED intent but reserve no extra capital."""
        if not str(exit_reason).strip():
            raise ValueError("exit_reason is required")

        intents = self.tables["order_intents"]
        trades = self.tables["open_trades"]
        closed = self.tables["closed_trades"]
        positions = self.tables["active_positions"]

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

        if conn.execute(
            sa.select(closed.c.trade_id).where(closed.c.trade_id == trade_id)
        ).first() is not None:
            return {
                "ok": True,
                "duplicate": True,
                "trade_id": trade_id,
                "state": "FLAT",
            }

        trade = conn.execute(
            sa.select(trades)
            .where(trades.c.trade_id == trade_id)
            .with_for_update()
        ).mappings().first()
        if trade is None:
            return {"ok": False, "error": "trade_not_open"}

        active = conn.execute(
            sa.select(positions)
            .where(positions.c.position_key == trade["position_key"])
            .with_for_update()
        ).mappings().first()
        if active is None or active["trade_id"] != trade_id:
            return {"ok": False, "error": "trade_not_open"}

        opening_intent = conn.execute(
            sa.select(intents).where(
                intents.c.order_intent_id == trade["order_intent_id"]
            )
        ).mappings().one()

        exit_plan_payload = dict(trade["exit_plan_payload"] or {})
        hard_stop_price = exit_plan_payload.get("hard_stop_price")
        timeout_at = created_at_utc + timedelta(milliseconds=15_000)

        conn.execute(
            intents.insert().values(
                order_intent_id=order_intent_id,
                broker_account_id=opening_intent["broker_account_id"],
                exit_plan_id=trade["exit_plan_id"],
                intent_kind="CLOSE",
                exit_reason=str(exit_reason),
                position_key=trade["position_key"],
                signal_key=opening_intent["signal_key"],
                reserved_cash_usd=0.0,
                reserved_margin_usd=0.0,
                ready_spread_bps=ready_spread_bps,
                hard_stop_price=hard_stop_price,
                submit_timeout_at=timeout_at,
                fill_market_observation_id=None,
                trade_id=trade_id,
                row_version=1,
                ticket_id=trade["ticket_id"],
                firm_event_id=trade["firm_event_id"],
                asset_id=trade["asset_id"],
                route_id=trade["route_id"],
                broker=opening_intent["broker"],
                venue=opening_intent["venue"],
                symbol=opening_intent["symbol"],
                side=trade["side"],
                qty=trade["quantity"],
                order_type="market",
                reference_price=reference_price,
                expected_fill=None,
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
                policy_version=trade["policy_version"],
                configuration_hash=trade["configuration_hash"],
                market_observation_id=market_observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=created_at_utc,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="order_intent",
            aggregate_id=order_intent_id,
            prior_state="FLATTEN_REQUEST",
            new_state="RESERVED",
            seat="Portfolio",
            reason_code="portfolio.flatten_reserve",
            policy_version=trade["policy_version"],
            configuration_hash=trade["configuration_hash"],
            market_observation_id=market_observation_id,
            actor=actor,
            created_at_utc=created_at_utc,
            payload={
                "trade_id": trade_id,
                "position_key": trade["position_key"],
                "exit_reason": str(exit_reason),
                "reserved_cash_usd": 0.0,
                "reserved_margin_usd": 0.0,
                "opening_reservation_retained": True,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "order_intent_id": order_intent_id,
            "state": "RESERVED",
        }

    def finalize_filled_flat(
        self,
        conn: Connection,
        *,
        close_order_intent_id: str,
        fill_market_observation_id: str,
        filled_at_utc: datetime,
        filled_qty: float,
        exit_price: float,
        gross_pnl_usd: float,
        net_pnl_usd: float,
        total_cost_usd: float,
        fees_usd: float,
        slippage_usd: float,
        slippage_bps: float,
        mfe_usd: float | None,
        mae_usd: float | None,
        capture_efficiency: float | None,
        event_id: str,
        actor: str = "Portfolio",
    ) -> dict[str, Any]:
        """Atomically commit CLOSE FILLED -> FLAT and release the OPEN reservation."""
        if filled_qty <= 0 or exit_price <= 0:
            raise ValueError("filled quantity and exit price must be positive")
        if total_cost_usd < 0 or fees_usd < 0:
            raise ValueError("costs and fees cannot be negative")
        if fees_usd > total_cost_usd + 1e-9:
            raise ValueError("fees_usd cannot exceed total_cost_usd")

        intents = self.tables["order_intents"]
        trades = self.tables["open_trades"]
        closed = self.tables["closed_trades"]
        positions = self.tables["active_positions"]
        ledgers = self.tables["broker_account_ledgers"]
        lineage = self.tables["decision_lineage"]

        close_intent = conn.execute(
            sa.select(intents)
            .where(intents.c.order_intent_id == close_order_intent_id)
            .with_for_update()
        ).mappings().first()
        if close_intent is None:
            raise KeyError(f"unknown close intent: {close_order_intent_id}")

        trade_id = str(close_intent["trade_id"] or "")
        if not trade_id:
            raise ValueError("CLOSE intent must reference trade_id")

        existing_closed = conn.execute(
            sa.select(closed).where(closed.c.trade_id == trade_id)
        ).mappings().first()
        if existing_closed is not None:
            return {
                "ok": True,
                "duplicate": True,
                "state": "FLAT",
                "trade_id": trade_id,
            }

        if close_intent["state"] in {
            "REJECTED",
            "CANCELLED",
            "CANCELLED_STALE",
        }:
            return {
                "ok": False,
                "duplicate": True,
                "error": "terminal_state_wins",
                "state": close_intent["state"],
            }
        if close_intent["state"] != "SUBMITTED":
            return {
                "ok": False,
                "error": "illegal_state",
                "state": close_intent["state"],
            }
        if close_intent["intent_kind"] != "CLOSE":
            return {
                "ok": False,
                "error": "illegal_intent_kind",
                "state": close_intent["state"],
            }

        trade = conn.execute(
            sa.select(trades)
            .where(trades.c.trade_id == trade_id)
            .with_for_update()
        ).mappings().one()
        if abs(float(filled_qty) - float(trade["quantity"])) > 1e-12:
            return {
                "ok": False,
                "error": "partial_fill_disabled",
                "state": close_intent["state"],
            }

        active = conn.execute(
            sa.select(positions)
            .where(positions.c.position_key == trade["position_key"])
            .with_for_update()
        ).mappings().first()
        if active is None or active["trade_id"] != trade_id:
            return {
                "ok": False,
                "error": "trade_not_open",
                "state": close_intent["state"],
            }

        opening_intent = conn.execute(
            sa.select(intents).where(
                intents.c.order_intent_id == trade["order_intent_id"]
            )
        ).mappings().one()
        ledger = conn.execute(
            sa.select(ledgers)
            .where(
                ledgers.c.broker_account_id
                == opening_intent["broker_account_id"]
            )
            .with_for_update()
        ).mappings().one()

        reserve_cash = float(opening_intent["reserved_cash_usd"])
        reserve_margin = float(opening_intent["reserved_margin_usd"])
        cash_reserved = float(ledger["cash_reserved_usd"])
        margin_used = float(ledger["margin_used_usd"])
        if cash_reserved + 1e-9 < reserve_cash:
            raise RuntimeError("cash reservation drift")
        if margin_used + 1e-9 < reserve_margin:
            raise RuntimeError("margin reservation drift")

        post_cash = (
            float(ledger["cash_available_usd"])
            + reserve_cash
            + float(net_pnl_usd)
        )
        if post_cash < -1e-9:
            raise RuntimeError("flat would violate nonnegative sleeve cash law")
        post_cash = max(0.0, post_cash)

        opened_at = _stored_utc(trade["opened_at_utc"])
        closed_at = _stored_utc(filled_at_utc)
        assert opened_at is not None and closed_at is not None
        duration_s = (closed_at - opened_at).total_seconds()
        if duration_s < 0:
            raise ValueError("close cannot precede open")

        exit_reason = str(close_intent["exit_reason"] or "")
        if not exit_reason:
            raise ValueError("CLOSE intent missing exit_reason")

        conn.execute(
            closed.insert().values(
                trade_id=trade_id,
                firm_event_id=trade["firm_event_id"],
                route_id=trade["route_id"],
                asset_id=trade["asset_id"],
                position_key=trade["position_key"],
                side=trade["side"],
                quantity=trade["quantity"],
                avg_entry_price=trade["avg_entry_price"],
                exit_price=exit_price,
                closed_at_utc=filled_at_utc,
                gross_pnl_usd=gross_pnl_usd,
                net_pnl_usd=net_pnl_usd,
                total_cost_usd=total_cost_usd,
                fees_usd=fees_usd,
                mfe_usd=mfe_usd,
                mae_usd=mae_usd,
                capture_efficiency=capture_efficiency,
                duration_s=duration_s,
                exit_reason=exit_reason,
                policy_version=trade["policy_version"],
                configuration_hash=trade["configuration_hash"],
                market_observation_id=fill_market_observation_id,
            )
        )
        conn.execute(
            positions.delete().where(
                sa.and_(
                    positions.c.position_key == trade["position_key"],
                    positions.c.trade_id == trade_id,
                )
            )
        )
        conn.execute(
            ledgers.update()
            .where(
                ledgers.c.broker_account_id
                == opening_intent["broker_account_id"]
            )
            .values(
                cash_available_usd=post_cash,
                cash_reserved_usd=cash_reserved - reserve_cash,
                margin_used_usd=margin_used - reserve_margin,
                margin_available_usd=(
                    float(ledger["margin_available_usd"]) + reserve_margin
                ),
                realized_pnl_usd=(
                    float(ledger["realized_pnl_usd"]) + float(net_pnl_usd)
                ),
                fees_accrued_usd=(
                    float(ledger["fees_accrued_usd"]) + float(fees_usd)
                ),
                settled_cash_usd=post_cash,
                row_version=int(ledger["row_version"]) + 1,
            )
        )
        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == close_order_intent_id)
            .values(
                state="FILLED",
                filled_at=filled_at_utc,
                filled_qty=filled_qty,
                avg_fill_price=exit_price,
                reject_code=None,
                slippage_usd=slippage_usd,
                slippage_bps=slippage_bps,
                fill_market_observation_id=fill_market_observation_id,
                row_version=int(close_intent["row_version"]) + 1,
            )
        )

        firm_event_id = trade["firm_event_id"]
        if firm_event_id:
            conn.execute(
                lineage.update()
                .where(lineage.c.firm_event_id == firm_event_id)
                .values(
                    market_observation_id=fill_market_observation_id,
                    row_version=lineage.c.row_version + 1,
                )
            )

        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="trade",
            aggregate_id=trade_id,
            prior_state="OPEN",
            new_state="FLAT",
            seat="Portfolio",
            reason_code=exit_reason,
            policy_version=trade["policy_version"],
            configuration_hash=trade["configuration_hash"],
            market_observation_id=fill_market_observation_id,
            actor=actor,
            created_at_utc=filled_at_utc,
            payload={
                "close_order_intent_id": close_order_intent_id,
                "position_key": trade["position_key"],
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "gross_pnl_usd": gross_pnl_usd,
                "net_pnl_usd": net_pnl_usd,
                "total_cost_usd": total_cost_usd,
                "fees_usd": fees_usd,
                "released_cash_usd": reserve_cash,
                "released_margin_usd": reserve_margin,
                "signal_remains_consumed": True,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "state": "FLAT",
            "trade_id": trade_id,
            "position_key": trade["position_key"],
            "net_pnl_usd": float(net_pnl_usd),
        }

    def stale_order_intent_ids(
        self,
        conn: Connection,
        *,
        at_utc: datetime,
    ) -> tuple[str, ...]:
        """Return RESERVED/SUBMITTED intents whose durable timeout has elapsed."""
        intents = self.tables["order_intents"]
        rows = conn.execute(
            sa.select(intents.c.order_intent_id).where(
                sa.and_(
                    intents.c.state.in_(("RESERVED", "SUBMITTED")),
                    intents.c.submit_timeout_at.is_not(None),
                    intents.c.submit_timeout_at < at_utc,
                )
            )
        )
        return tuple(str(row[0]) for row in rows)

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
