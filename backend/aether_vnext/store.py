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
    QualityState,
)
from aether_vnext.equity import (
    FirmEquityProjection,
    SleeveEquityProjection,
    conservative_mark_price,
    conservative_unrealized_pnl_usd,
    firm_equity_projection,
    inventory_market_value_usd,
    sleeve_equity_projection,
)
from aether_vnext.registry import ProductType, registry_row
from aether_vnext.reservations import reservation_requirement
from aether_vnext.risk import (
    BookRiskPosition,
    BookRiskSnapshot,
    RiskExposure,
    aggregate_book_risk,
    risk_limits_usd,
    stop_risk_usd,
)
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.schema import build_metadata
from aether_vnext.seed_truth import ASSET_BROKER_ACCOUNT


SEED_LEDGER_CASH_USD: Mapping[str, float] = {
    "kraken_paper": 4000.0,
    "tastyfx_paper": 2000.0,
    "ninja_paper": 2000.0,
    "ibkr_paper": 2000.0,
}


GOVERNOR_SCOPE_TYPES = frozenset({"route", "venue", "product", "desk"})
GOVERNOR_HALT_REASON_BY_SCOPE: Mapping[str, str] = {
    "route": ReasonCode.ROUTE_HALTED.value,
    "venue": ReasonCode.VENUE_HALTED.value,
    # The Master reason dictionary defines lifecycle_ineligible as including
    # a halted instrument; no separate product_halted code is invented.
    "product": ReasonCode.LIFECYCLE_INELIGIBLE.value,
    "desk": ReasonCode.DESK_HALTED.value,
}


def open_intent_idempotency_key(
    *,
    ticket_id: str,
    side: str,
    quantity: float,
    asset_id: str,
    horizon: str,
    signal_key: str,
) -> str:
    """Binding v3.1/Part III OPEN-intent idempotency formula."""
    raw = "|".join(
        (
            str(ticket_id),
            str(side),
            str(quantity),
            str(asset_id),
            str(horizon),
            str(signal_key),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _uses_cash_inventory(asset_id: str, side: str) -> bool:
    row = registry_row(asset_id)
    return (
        str(side).strip().lower() == "long"
        and row.product_type in {
            ProductType.SPOT_CRYPTO,
            ProductType.EQUITY,
        }
    )


def _upsert_cash_inventory(
    conn: Connection,
    *,
    table: sa.Table,
    broker_account_id: str,
    asset_id: str,
    quantity: float,
    avg_fill_price: float,
    updated_at_utc: datetime,
) -> None:
    existing = conn.execute(
        sa.select(table)
        .where(
            sa.and_(
                table.c.broker_account_id == broker_account_id,
                table.c.asset_id == asset_id,
            )
        )
        .with_for_update()
    ).mappings().first()

    if existing is None:
        conn.execute(
            table.insert().values(
                broker_account_id=broker_account_id,
                asset_id=asset_id,
                inventory_qty=quantity,
                inventory_avg=avg_fill_price,
                updated_at_utc=updated_at_utc,
                row_version=1,
            )
        )
        return

    old_qty = float(existing["inventory_qty"])
    old_avg = float(existing["inventory_avg"])
    new_qty = old_qty + float(quantity)
    if new_qty <= 0:
        raise RuntimeError("inventory quantity must remain positive on OPEN")
    new_avg = (
        old_qty * old_avg + float(quantity) * float(avg_fill_price)
    ) / new_qty
    conn.execute(
        table.update()
        .where(
            sa.and_(
                table.c.broker_account_id == broker_account_id,
                table.c.asset_id == asset_id,
            )
        )
        .values(
            inventory_qty=new_qty,
            inventory_avg=new_avg,
            updated_at_utc=updated_at_utc,
            row_version=int(existing["row_version"]) + 1,
        )
    )


def _reduce_cash_inventory(
    conn: Connection,
    *,
    table: sa.Table,
    broker_account_id: str,
    asset_id: str,
    quantity: float,
    trade_entry_price: float,
    updated_at_utc: datetime,
) -> None:
    existing = conn.execute(
        sa.select(table)
        .where(
            sa.and_(
                table.c.broker_account_id == broker_account_id,
                table.c.asset_id == asset_id,
            )
        )
        .with_for_update()
    ).mappings().first()
    if existing is None:
        raise RuntimeError("cash inventory missing for OPEN trade")

    old_qty = float(existing["inventory_qty"])
    old_avg = float(existing["inventory_avg"])
    remove_qty = float(quantity)
    if old_qty + 1e-9 < remove_qty:
        raise RuntimeError("cash inventory quantity drift")

    new_qty = old_qty - remove_qty
    if new_qty <= 1e-12:
        conn.execute(
            table.delete().where(
                sa.and_(
                    table.c.broker_account_id == broker_account_id,
                    table.c.asset_id == asset_id,
                )
            )
        )
        return

    remaining_cost = (
        old_qty * old_avg
        - remove_qty * float(trade_entry_price)
    )
    if remaining_cost <= 0:
        raise RuntimeError("cash inventory average-cost drift")
    new_avg = remaining_cost / new_qty
    conn.execute(
        table.update()
        .where(
            sa.and_(
                table.c.broker_account_id == broker_account_id,
                table.c.asset_id == asset_id,
            )
        )
        .values(
            inventory_qty=new_qty,
            inventory_avg=new_avg,
            updated_at_utc=updated_at_utc,
            row_version=int(existing["row_version"]) + 1,
        )
    )


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
        guard = self.tables["risk_admission_guard"]
        conn.execute(
            guard.insert().values(
                scope_key="firm",
                row_version=1,
                updated_at_utc=datetime.now(timezone.utc),
            )
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
                market_observation_id=row["observation_id_at_reserve"],
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
            symbol_executed=row["symbol_executed"],
            side=row["side"],
            requested_qty=float(row["requested_qty"]),
            order_type=row["order_type"],
            reference_price=row["reference_price"],
            expected_fill_price=row["expected_fill_price"],
            state=OrderIntentState(row["state"]),
            submitted_at=_stored_utc(row["submitted_at"]),
            acknowledged_at=_stored_utc(row["acknowledged_at"]),
            filled_at=_stored_utc(row["filled_at"]),
            filled_qty=float(row["filled_qty"]),
            avg_fill_price=row["avg_fill_price"],
            reject_code=row["reject_code"],
            slip_usd=row["slip_usd"],
            slip_bps=row["slip_bps"],
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
            observation_id_at_reserve=row["observation_id_at_reserve"],
            observation_id_at_fill=row["observation_id_at_fill"],
            trade_id=row["trade_id"],
            version=int(row["version"]),
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

    def _pending_open_risk_exposure(
        self,
        conn: Connection,
        *,
        asset_id: str,
        cluster_id: str,
    ) -> RiskExposure:
        intents = self.tables["order_intents"]
        reservations = self.tables["risk_admission_reservations"]

        rows = conn.execute(
            sa.select(
                intents.c.order_intent_id,
                reservations.c.asset_id,
                reservations.c.cluster_id,
                reservations.c.stop_risk_usd,
            )
            .select_from(
                intents.outerjoin(
                    reservations,
                    reservations.c.order_intent_id
                    == intents.c.order_intent_id,
                )
            )
            .where(
                sa.and_(
                    intents.c.intent_kind == "OPEN",
                    intents.c.state.in_(("RESERVED", "SUBMITTED")),
                )
            )
            .order_by(intents.c.order_intent_id)
        ).mappings().all()

        asset_risk = 0.0
        cluster_risk = 0.0
        portfolio_risk = 0.0
        for row in rows:
            if row["stop_risk_usd"] is None:
                raise RuntimeError(
                    "pending OPEN intent missing atomic risk reservation: "
                    f"{row['order_intent_id']}"
                )
            risk = float(row["stop_risk_usd"])
            if risk <= 0:
                raise RuntimeError(
                    f"invalid pending stop-risk: {row['order_intent_id']}"
                )
            portfolio_risk += risk
            if str(row["asset_id"]) == asset_id:
                asset_risk += risk
            if str(row["cluster_id"]) == cluster_id:
                cluster_risk += risk

        return RiskExposure(
            asset_open_risk_usd=asset_risk,
            cluster_open_risk_usd=cluster_risk,
            portfolio_open_risk_usd=portfolio_risk,
        )

    def reserve_risk_checked_open_intent(
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
        reserve_cash_usd: float | None,
        reserve_margin_usd: float | None,
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
        risk_cluster_id: str,
        cluster_by_asset: Mapping[str, str],
        current_observations: Mapping[str, MarketObservation],
        desk_scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically verify Firm risk and reserve an OPEN OrderIntent.

        A single durable Firm guard row is locked first. While that row is held,
        the method combines active-book stop-risk with every RESERVED/SUBMITTED
        OPEN risk reservation, checks the candidate against the frozen trade,
        asset, cluster and portfolio ceilings, and only then creates RESERVED.

        This prevents concurrent Phase-A admissions from spending the same risk
        capacity. Cluster identity remains explicit input until a canonical vNext
        twelve-asset cluster map is frozen.
        """
        cluster_id = str(risk_cluster_id).strip()
        if not cluster_id:
            raise ValueError("risk_cluster_id cannot be blank")

        intents = self.tables["order_intents"]
        risk_reservations = self.tables["risk_admission_reservations"]
        existing = conn.execute(
            sa.select(intents).where(
                intents.c.idempotency_key == idempotency_key
            )
        ).mappings().first()
        if existing is not None:
            if (
                existing["intent_kind"] == "OPEN"
                and existing["state"] in {"RESERVED", "SUBMITTED"}
            ):
                tracked = conn.execute(
                    sa.select(risk_reservations.c.order_intent_id).where(
                        risk_reservations.c.order_intent_id
                        == existing["order_intent_id"]
                    )
                ).first()
                if tracked is None:
                    raise RuntimeError(
                        "pending OPEN idempotent retry lacks risk reservation"
                    )
            return {
                "ok": True,
                "duplicate": True,
                "order_intent_id": existing["order_intent_id"],
                "state": existing["state"],
            }

        guard_table = self.tables["risk_admission_guard"]
        guard = conn.execute(
            sa.select(guard_table)
            .where(guard_table.c.scope_key == "firm")
            .with_for_update()
        ).mappings().first()
        if guard is None:
            raise RuntimeError(
                "Firm risk admission guard is not provisioned"
            )

        tickets = self.tables["tickets"]
        observations = self.tables["market_observations"]
        ticket = conn.execute(
            sa.select(tickets).where(tickets.c.ticket_id == ticket_id)
        ).mappings().first()

        # Let the existing Phase-A contract own canonical rejection behavior
        # when the ticket cannot be risk-evaluated as a valid READY candidate.
        preflight_valid = (
            ticket is not None
            and ticket["state"] == "READY"
            and ticket["asset_id"] == asset_id
            and ticket["route_id"] == route_id
            and ticket["signal_key"] == signal_key
            and ticket["side"] == side
            and ticket["exit_plan_id"] == exit_plan_id
            and ticket["stop_price"] is not None
            and ticket["quantity"] is not None
            and abs(float(ticket["quantity"]) - float(qty)) <= 1e-12
            and ticket["modeled_round_trip_cost_pct"] is not None
            and ticket["policy_version"] == policy_version
            and ticket["configuration_hash"] == configuration_hash
        )
        observation = conn.execute(
            sa.select(observations).where(
                observations.c.observation_id == market_observation_id
            )
        ).mappings().first()
        preflight_valid = bool(
            preflight_valid
            and observation is not None
            and observation["asset_id"] == asset_id
            and observation["quality_state"] == "healthy"
            and observation["bid"] is not None
            and observation["ask"] is not None
        )

        if not preflight_valid:
            return self.reserve_order_intent(
                conn,
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
                idempotency_key=idempotency_key,
                signal_key=signal_key,
                position_key=position_key,
                reserve_cash_usd=reserve_cash_usd,
                reserve_margin_usd=reserve_margin_usd,
                ready_spread_bps=ready_spread_bps,
                hard_stop_price=hard_stop_price,
                exit_plan_id=exit_plan_id,
                submit_timeout_at=submit_timeout_at,
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                market_observation_id=market_observation_id,
                created_at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                intent_kind="OPEN",
            )

        governor_block = self.governor_block_for_admission(
            conn,
            route_id=route_id,
            venue=venue,
            product_id=asset_id,
            desk_scope_id=desk_scope_id,
        )
        if governor_block is not None:
            return self.reject_ticket_governor_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code=str(governor_block["reason_code"]),
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
                governor_scope_key=str(governor_block["scope_key"]),
            )

        ticket_stop = float(ticket["stop_price"])
        if (
            hard_stop_price is None
            or abs(float(hard_stop_price) - ticket_stop) > 1e-12
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

        requirement = reservation_requirement(
            registry_row(asset_id),
            side=side,
            qty=float(qty),
            bid=float(observation["bid"]),
            ask=float(observation["ask"]),
            modeled_round_trip_cost_pct=float(
                ticket["modeled_round_trip_cost_pct"]
            ),
        )
        try:
            candidate_risk = stop_risk_usd(
                registry_row(asset_id),
                side=side,
                quantity=float(qty),
                entry_price=requirement.computed_entry_price,
                stop_price=ticket_stop,
            )
        except ValueError as exc:
            if str(exc) != "bad_stop":
                raise
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="bad_stop",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        firm_equity = self.project_firm_equity(
            conn,
            observations=current_observations,
        )
        if firm_equity.consolidated_equity_usd <= 0:
            raise RuntimeError("Firm equity must be positive for risk admission")
        limits = risk_limits_usd(firm_equity.consolidated_equity_usd)

        open_snapshot = self.project_open_risk(
            conn,
            cluster_by_asset=cluster_by_asset,
        )
        open_exposure = open_snapshot.exposure_for(
            asset_id=asset_id,
            cluster_id=cluster_id,
        )
        pending_exposure = self._pending_open_risk_exposure(
            conn,
            asset_id=asset_id,
            cluster_id=cluster_id,
        )
        exposure = RiskExposure(
            asset_open_risk_usd=(
                open_exposure.asset_open_risk_usd
                + pending_exposure.asset_open_risk_usd
            ),
            cluster_open_risk_usd=(
                open_exposure.cluster_open_risk_usd
                + pending_exposure.cluster_open_risk_usd
            ),
            portfolio_open_risk_usd=(
                open_exposure.portfolio_open_risk_usd
                + pending_exposure.portfolio_open_risk_usd
            ),
        )

        epsilon = 1e-6
        if candidate_risk > limits.trade_usd + epsilon:
            # A READY ticket above the constitutional per-trade ceiling is an
            # invalid upstream ticket contract; no new non-canonical reason code
            # is invented here.
            reason_code = "ticket_contract_mismatch"
        elif (
            exposure.asset_open_risk_usd + candidate_risk
            > limits.asset_usd + epsilon
        ):
            reason_code = "asset_risk_full"
        elif (
            exposure.cluster_open_risk_usd + candidate_risk
            > limits.cluster_usd + epsilon
        ):
            reason_code = "cluster_risk_full"
        elif (
            exposure.portfolio_open_risk_usd + candidate_risk
            > limits.portfolio_usd + epsilon
        ):
            reason_code = "portfolio_risk_full"
        else:
            reason_code = None

        if reason_code is not None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code=reason_code,
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        result = self.reserve_order_intent(
            conn,
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
            idempotency_key=idempotency_key,
            signal_key=signal_key,
            position_key=position_key,
            reserve_cash_usd=reserve_cash_usd,
            reserve_margin_usd=reserve_margin_usd,
            ready_spread_bps=ready_spread_bps,
            hard_stop_price=hard_stop_price,
            exit_plan_id=exit_plan_id,
            submit_timeout_at=submit_timeout_at,
            policy_version=policy_version,
            configuration_hash=configuration_hash,
            market_observation_id=market_observation_id,
            created_at_utc=created_at_utc,
            event_id=event_id,
            actor=actor,
            intent_kind="OPEN",
        )
        if not result.get("ok") or result.get("duplicate"):
            return result

        conn.execute(
            risk_reservations.insert().values(
                order_intent_id=order_intent_id,
                asset_id=asset_id,
                cluster_id=cluster_id,
                stop_risk_usd=candidate_risk,
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                created_at_utc=created_at_utc,
            )
        )
        conn.execute(
            guard_table.update()
            .where(guard_table.c.scope_key == "firm")
            .values(
                row_version=int(guard["row_version"]) + 1,
                updated_at_utc=created_at_utc,
            )
        )
        return result | {
            "reserved_stop_risk_usd": candidate_risk,
            "risk_cluster_id": cluster_id,
            "firm_equity_usd": firm_equity.consolidated_equity_usd,
        }

    def set_governor_state(
        self,
        conn: Connection,
        *,
        scope_key: str,
        scope_type: str,
        scope_id: str | None,
        state: str,
        governor_state_version: str,
        policy_version: str,
        configuration_hash: str,
        effective_at_utc: datetime,
        reason: str,
        actor: str,
        authenticated: bool,
        expected_row_version: int | None = None,
        event_id: str,
    ) -> dict[str, Any]:
        """Persist an authenticated Governor state transition with audit history.

        NORMAL/HALT is independent of Review KEEP/BENCH. Restart never invokes
        this mutation; the durable row remains authoritative until another
        authenticated transition explicitly changes it.
        """
        normalized_scope = str(scope_type).strip().lower()
        normalized_state = str(state).strip().upper()
        normalized_key = str(scope_key).strip()
        normalized_actor = str(actor).strip()
        normalized_reason = str(reason).strip()
        version = str(governor_state_version).strip()

        if normalized_scope not in GOVERNOR_SCOPE_TYPES:
            raise ValueError("unsupported Governor scope_type")
        if normalized_state not in {"NORMAL", "HALT"}:
            raise ValueError("Governor state must be NORMAL or HALT")
        if not normalized_key:
            raise ValueError("scope_key cannot be blank")
        if normalized_scope != "desk" and not str(scope_id or "").strip():
            raise ValueError(f"{normalized_scope} scope requires scope_id")
        if not version:
            raise ValueError("governor_state_version cannot be blank")
        if not normalized_reason:
            raise ValueError("Governor transition reason cannot be blank")
        if not normalized_actor:
            raise ValueError("Governor transition actor cannot be blank")
        if not authenticated:
            raise PermissionError("Governor transition requires authenticated actor")

        table = self.tables["governor_state"]
        existing = conn.execute(
            sa.select(table)
            .where(table.c.scope_key == normalized_key)
            .with_for_update()
        ).mappings().first()

        prior_state: str | None = None
        if existing is None:
            if expected_row_version not in {None, 0}:
                raise RuntimeError("Governor optimistic version mismatch")
            conn.execute(
                table.insert().values(
                    scope_key=normalized_key,
                    scope_type=normalized_scope,
                    scope_id=(
                        str(scope_id).strip()
                        if scope_id is not None
                        else None
                    ),
                    governor_state_version=version,
                    state=normalized_state,
                    configuration_hash=configuration_hash,
                    effective_at_utc=effective_at_utc,
                    reason=normalized_reason,
                    row_version=1,
                )
            )
            row_version = 1
        else:
            prior_state = str(existing["state"])
            if (
                expected_row_version is not None
                and int(existing["row_version"]) != int(expected_row_version)
            ):
                raise RuntimeError("Governor optimistic version mismatch")
            if str(existing["scope_type"]) != normalized_scope:
                raise RuntimeError("Governor scope_type cannot change in place")
            existing_scope_id = (
                str(existing["scope_id"]).strip()
                if existing["scope_id"] is not None
                else None
            )
            requested_scope_id = (
                str(scope_id).strip()
                if scope_id is not None
                else None
            )
            if existing_scope_id != requested_scope_id:
                raise RuntimeError("Governor scope_id cannot change in place")
            row_version = int(existing["row_version"]) + 1
            conn.execute(
                table.update()
                .where(table.c.scope_key == normalized_key)
                .values(
                    governor_state_version=version,
                    state=normalized_state,
                    configuration_hash=configuration_hash,
                    effective_at_utc=effective_at_utc,
                    reason=normalized_reason,
                    row_version=row_version,
                )
            )

        halt_reason = GOVERNOR_HALT_REASON_BY_SCOPE[normalized_scope]
        audit_code = (
            halt_reason
            if normalized_state == "HALT"
            else "governor_reset"
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="governor_state",
            aggregate_id=normalized_key,
            prior_state=prior_state,
            new_state=normalized_state,
            seat="Governor",
            reason_code=audit_code,
            policy_version=policy_version,
            configuration_hash=configuration_hash,
            market_observation_id=None,
            actor=normalized_actor,
            created_at_utc=effective_at_utc,
            payload={
                "scope_type": normalized_scope,
                "scope_id": (
                    str(scope_id).strip()
                    if scope_id is not None
                    else None
                ),
                "reason": normalized_reason,
                "authenticated": True,
                "governor_state_version": version,
                "row_version": row_version,
            },
        )
        return {
            "scope_key": normalized_key,
            "scope_type": normalized_scope,
            "scope_id": (
                str(scope_id).strip()
                if scope_id is not None
                else None
            ),
            "state": normalized_state,
            "row_version": row_version,
            "reason": normalized_reason,
        }

    def governor_block_for_admission(
        self,
        conn: Connection,
        *,
        route_id: str,
        venue: str,
        product_id: str,
        desk_scope_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the earliest-effective matching durable HALT, if any."""
        table = self.tables["governor_state"]
        rows = conn.execute(
            sa.select(table)
            .where(table.c.state == "HALT")
            .order_by(
                table.c.effective_at_utc,
                table.c.scope_key,
            )
        ).mappings().all()

        route_value = str(route_id).strip()
        venue_value = str(venue).strip()
        product_value = str(product_id).strip()
        desk_value = (
            str(desk_scope_id).strip()
            if desk_scope_id is not None
            else None
        )

        for row in rows:
            scope_type = str(row["scope_type"]).strip().lower()
            if scope_type not in GOVERNOR_SCOPE_TYPES:
                raise RuntimeError(
                    f"unsupported durable Governor scope: {scope_type}"
                )
            scope_id = (
                str(row["scope_id"]).strip()
                if row["scope_id"] is not None
                else None
            )
            matches = (
                (scope_type == "route" and scope_id == route_value)
                or (scope_type == "venue" and scope_id == venue_value)
                or (scope_type == "product" and scope_id == product_value)
                or (
                    scope_type == "desk"
                    and (
                        scope_id is None
                        or (
                            desk_value is not None
                            and scope_id == desk_value
                        )
                    )
                )
            )
            if matches:
                return {
                    "scope_key": row["scope_key"],
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "reason_code": GOVERNOR_HALT_REASON_BY_SCOPE[scope_type],
                    "reason": row["reason"],
                    "effective_at_utc": row["effective_at_utc"],
                }
        return None

    def reject_ticket_governor_pre_reserve(
        self,
        conn: Connection,
        *,
        ticket_id: str,
        reason_code: str,
        at_utc: datetime,
        event_id: str,
        actor: str,
        market_observation_id: str | None = None,
        governor_scope_key: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Governor veto before any OrderIntent or capital reservation."""
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

        observation_id = market_observation_id or row["market_observation_id"]
        conn.execute(
            tickets.update()
            .where(tickets.c.ticket_id == ticket_id)
            .values(
                state="REJECTED",
                reject_code=reason_code,
                first_killed_by="Governor",
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
            seat="Governor",
            reason_code=reason_code,
            policy_version=row["policy_version"],
            configuration_hash=row["configuration_hash"],
            market_observation_id=observation_id,
            actor=actor,
            created_at_utc=at_utc,
            payload={
                "first_killed_by": "Governor",
                "first_kill_reason": reason_code,
                "governor_scope_key": governor_scope_key,
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
        reserve_cash_usd: float | None,
        reserve_margin_usd: float | None,
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

        if submit_timeout_at is None:
            submit_timeout_at = created_at_utc + timedelta(milliseconds=15_000)

        intents = self.tables["order_intents"]
        ledgers = self.tables["broker_account_ledgers"]
        signals = self.tables["signal_consumptions"]
        positions = self.tables["active_positions"]
        tickets = self.tables["tickets"]
        observations = self.tables["market_observations"]

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
        canonical_broker_account_id = ASSET_BROKER_ACCOUNT.get(asset_id)
        if canonical_broker_account_id is None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="unsupported_product",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        if broker_account_id != canonical_broker_account_id:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="broker_sleeve_mismatch",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        expected_idempotency_key = open_intent_idempotency_key(
            ticket_id=ticket_id,
            side=side,
            quantity=float(ticket["quantity"]),
            asset_id=asset_id,
            horizon=str(ticket["horizon"]),
            signal_key=signal_key,
        )
        if idempotency_key != expected_idempotency_key:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="idempotency_key_mismatch",
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

        observation = conn.execute(
            sa.select(observations).where(
                observations.c.observation_id == market_observation_id
            )
        ).mappings().first()
        if observation is None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="market_observation_missing",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        if observation["asset_id"] != asset_id:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="market_observation_mismatch",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        if (
            observation["quality_state"] != "healthy"
            or observation["bid"] is None
            or observation["ask"] is None
        ):
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="market_invalid",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )
        modeled_cost_pct = ticket["modeled_round_trip_cost_pct"]
        if modeled_cost_pct is None:
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="cost_model_missing",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        requirement = reservation_requirement(
            registry_row(asset_id),
            side=side,
            qty=float(ticket["quantity"]),
            bid=float(observation["bid"]),
            ask=float(observation["ask"]),
            modeled_round_trip_cost_pct=float(modeled_cost_pct),
        )

        # Backward-compatible arguments are assertions only.  Portfolio owns the
        # actual reservation values and always stores the source-derived result.
        if (
            reserve_cash_usd is not None
            and abs(float(reserve_cash_usd) - requirement.reserve_cash_usd) > 1e-6
        ) or (
            reserve_margin_usd is not None
            and abs(float(reserve_margin_usd) - requirement.margin_need_usd) > 1e-6
        ):
            return self.reject_ticket_pre_reserve(
                conn,
                ticket_id=ticket_id,
                reason_code="reservation_mismatch",
                at_utc=created_at_utc,
                event_id=event_id,
                actor=actor,
                market_observation_id=market_observation_id,
            )

        reserve_cash_usd = requirement.reserve_cash_usd
        reserve_margin_usd = requirement.margin_need_usd
        reference_price = requirement.entry_reference_price
        expected_fill = requirement.computed_entry_price

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
                symbol_executed=symbol,
                side=side,
                requested_qty=qty,
                order_type="MARKET_PAPER",
                reference_price=reference_price,
                expected_fill_price=expected_fill,
                state="RESERVED",
                submitted_at=None,
                acknowledged_at=None,
                filled_at=None,
                filled_qty=0.0,
                avg_fill_price=None,
                reject_code=None,
                slip_usd=None,
                slip_bps=None,
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
                observation_id_at_fill=None,
                trade_id=None,
                version=1,
                policy_version=policy_version,
                configuration_hash=configuration_hash,
                observation_id_at_reserve=market_observation_id,
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
                "entry_reference_price": requirement.entry_reference_price,
                "computed_entry_price": requirement.computed_entry_price,
                "estimated_cost_buffer_usd": requirement.estimated_cost_buffer_usd,
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
                version=int(row["version"]) + 1,
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
            market_observation_id=row["observation_id_at_reserve"],
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
        inventory = self.tables["sleeve_inventory"]

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
        if abs(float(filled_qty) - float(intent["requested_qty"])) > 1e-12:
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
        if _uses_cash_inventory(intent["asset_id"], intent["side"]):
            _upsert_cash_inventory(
                conn,
                table=inventory,
                broker_account_id=intent["broker_account_id"],
                asset_id=intent["asset_id"],
                quantity=filled_qty,
                avg_fill_price=avg_fill_price,
                updated_at_utc=filled_at_utc,
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
                slip_usd=slippage_usd,
                slip_bps=slippage_bps,
                observation_id_at_fill=fill_market_observation_id,
                trade_id=trade_id,
                exit_plan_id=exit_plan_id,
                version=int(intent["version"]) + 1,
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
                observation_id_at_fill=None,
                trade_id=trade_id,
                version=1,
                ticket_id=trade["ticket_id"],
                firm_event_id=trade["firm_event_id"],
                asset_id=trade["asset_id"],
                route_id=trade["route_id"],
                broker=opening_intent["broker"],
                venue=opening_intent["venue"],
                symbol_executed=opening_intent["symbol_executed"],
                side=trade["side"],
                requested_qty=trade["quantity"],
                order_type="MARKET_PAPER",
                reference_price=reference_price,
                expected_fill_price=None,
                state="RESERVED",
                submitted_at=None,
                acknowledged_at=None,
                filled_at=None,
                filled_qty=0.0,
                avg_fill_price=None,
                reject_code=None,
                slip_usd=None,
                slip_bps=None,
                idempotency_key=idempotency_key,
                policy_version=trade["policy_version"],
                configuration_hash=trade["configuration_hash"],
                observation_id_at_reserve=market_observation_id,
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
        inventory = self.tables["sleeve_inventory"]

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

        if _uses_cash_inventory(trade["asset_id"], trade["side"]):
            _reduce_cash_inventory(
                conn,
                table=inventory,
                broker_account_id=opening_intent["broker_account_id"],
                asset_id=trade["asset_id"],
                quantity=filled_qty,
                trade_entry_price=float(trade["avg_entry_price"]),
                updated_at_utc=filled_at_utc,
            )

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
                slip_usd=slippage_usd,
                slip_bps=slippage_bps,
                observation_id_at_fill=fill_market_observation_id,
                version=int(close_intent["version"]) + 1,
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
        first_killed_by: str | None,
        fill_market_observation_id: str | None = None,
    ) -> dict[str, Any]:
        if terminal_state not in {"REJECTED", "CANCELLED", "CANCELLED_STALE"}:
            raise ValueError("terminal_state must release a zero-fill reservation")

        intents = self.tables["order_intents"]
        ledgers = self.tables["broker_account_ledgers"]
        tickets = self.tables["tickets"]
        lineage = self.tables["decision_lineage"]

        intent = conn.execute(
            sa.select(intents)
            .where(intents.c.order_intent_id == order_intent_id)
            .with_for_update()
        ).mappings().first()
        if intent is None:
            raise KeyError(f"unknown order intent: {order_intent_id}")
        if intent["state"] in {"FILLED", "REJECTED", "CANCELLED", "CANCELLED_STALE"}:
            return {"ok": True, "duplicate": True, "state": intent["state"]}

        is_failed_open = intent["intent_kind"] == "OPEN"
        if is_failed_open and first_killed_by not in {
            "Portfolio",
            "execution",
            "Governor",
        }:
            raise ValueError(
                "failed OPEN requires explicit first_killed_by "
                "(Portfolio, execution, or Governor)"
            )

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
        intent_values: dict[str, Any] = {
            "state": terminal_state,
            "reject_code": reject_code,
            "observation_id_at_fill": fill_market_observation_id,
            "version": int(intent["version"]) + 1,
        }
        if is_failed_open:
            intent_values["first_killed_by"] = (
                intent["first_killed_by"] or first_killed_by
            )
            intent_values["first_kill_reason"] = (
                intent["first_kill_reason"] or reject_code
            )
        conn.execute(
            intents.update()
            .where(intents.c.order_intent_id == order_intent_id)
            .values(**intent_values)
        )

        if is_failed_open:
            ticket = conn.execute(
                sa.select(tickets)
                .where(tickets.c.ticket_id == intent["ticket_id"])
                .with_for_update()
            ).mappings().one()
            conn.execute(
                tickets.update()
                .where(tickets.c.ticket_id == intent["ticket_id"])
                .values(
                    state="REJECTED",
                    reject_code=reject_code,
                    first_killed_by=(
                        ticket["first_killed_by"] or first_killed_by
                    ),
                    first_kill_reason=(
                        ticket["first_kill_reason"] or reject_code
                    ),
                    market_observation_id=(
                        fill_market_observation_id
                        or ticket["market_observation_id"]
                    ),
                )
            )

            firm_event_id = intent["firm_event_id"]
            if firm_event_id:
                lineage_row = conn.execute(
                    sa.select(lineage)
                    .where(lineage.c.firm_event_id == firm_event_id)
                    .with_for_update()
                ).mappings().first()
                if lineage_row is not None:
                    conn.execute(
                        lineage.update()
                        .where(lineage.c.firm_event_id == firm_event_id)
                        .values(
                            first_killed_by=(
                                lineage_row["first_killed_by"]
                                or first_killed_by
                            ),
                            first_kill_reason=(
                                lineage_row["first_kill_reason"]
                                or reject_code
                            ),
                            market_observation_id=(
                                fill_market_observation_id
                                or lineage_row["market_observation_id"]
                            ),
                            row_version=int(lineage_row["row_version"]) + 1,
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
                fill_market_observation_id or intent["observation_id_at_reserve"]
            ),
            actor=actor,
            created_at_utc=at_utc,
            payload={
                "released_cash_usd": reserve_cash,
                "released_margin_usd": reserve_margin,
                "first_killed_by": (
                    first_killed_by if is_failed_open else None
                ),
                "first_kill_reason": (
                    reject_code if is_failed_open else None
                ),
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

    def project_firm_equity(
        self,
        conn: Connection,
        *,
        observations: Mapping[str, MarketObservation],
    ) -> FirmEquityProjection:
        """Project conservative marked Firm equity from the durable book.

        Cash-purchase inventory is marked at bid and its backing opening reserve
        is removed once from cash_reserved before inventory MTM is added. Margin
        positions keep reserved cash as capital and contribute conservative
        unrealized P&L. Any OPEN asset without a HEALTHY current observation
        makes the projection unavailable rather than guessed.
        """
        ledgers = self.tables["broker_account_ledgers"]
        inventory = self.tables["sleeve_inventory"]
        active_positions = self.tables["active_positions"]
        trades = self.tables["open_trades"]
        intents = self.tables["order_intents"]

        ledger_rows = {
            str(row["broker_account_id"]): row
            for row in conn.execute(
                sa.select(ledgers).order_by(ledgers.c.broker_account_id)
            ).mappings()
        }
        if not ledger_rows:
            raise RuntimeError("no broker sleeve ledgers are provisioned")

        inventory_backing: dict[str, float] = {
            broker_id: 0.0 for broker_id in ledger_rows
        }
        inventory_mtm: dict[str, float] = {
            broker_id: 0.0 for broker_id in ledger_rows
        }
        non_inventory_unrealized: dict[str, float] = {
            broker_id: 0.0 for broker_id in ledger_rows
        }
        expected_inventory_qty: dict[tuple[str, str], float] = {}

        def require_observation(asset_id: str) -> MarketObservation:
            observation = observations.get(asset_id)
            if observation is None:
                raise ValueError(
                    f"missing current observation for OPEN asset: {asset_id}"
                )
            if observation.asset_id != asset_id:
                raise ValueError(
                    f"observation asset mismatch: expected {asset_id}, "
                    f"got {observation.asset_id}"
                )
            if observation.quality_state is not QualityState.HEALTHY:
                raise ValueError(
                    f"non-healthy observation for OPEN asset: {asset_id}"
                )
            if observation.bid is None or observation.ask is None:
                raise ValueError(
                    f"two-sided quote required for OPEN asset: {asset_id}"
                )
            # Validates positive/non-crossed book before any mark is accepted.
            conservative_mark_price(
                side="long",
                bid=float(observation.bid),
                ask=float(observation.ask),
            )
            return observation

        active_rows = conn.execute(
            sa.select(active_positions).order_by(active_positions.c.position_key)
        ).mappings().all()

        for active in active_rows:
            trade = conn.execute(
                sa.select(trades).where(
                    trades.c.trade_id == active["trade_id"]
                )
            ).mappings().one()
            opening_intent = conn.execute(
                sa.select(intents).where(
                    intents.c.order_intent_id == trade["order_intent_id"]
                )
            ).mappings().one()

            broker_id = str(opening_intent["broker_account_id"])
            if broker_id not in ledger_rows:
                raise RuntimeError(
                    f"OPEN trade references unknown broker sleeve: {broker_id}"
                )

            asset_id = str(trade["asset_id"])
            observation = require_observation(asset_id)

            if _uses_cash_inventory(asset_id, str(trade["side"])):
                inventory_backing[broker_id] += float(
                    opening_intent["reserved_cash_usd"]
                )
                key = (broker_id, asset_id)
                expected_inventory_qty[key] = (
                    expected_inventory_qty.get(key, 0.0)
                    + float(trade["quantity"])
                )
                continue

            non_inventory_unrealized[broker_id] += (
                conservative_unrealized_pnl_usd(
                    registry_row(asset_id),
                    side=str(trade["side"]),
                    quantity=float(trade["quantity"]),
                    avg_entry_price=float(trade["avg_entry_price"]),
                    bid=float(observation.bid),
                    ask=float(observation.ask),
                )
            )

        inventory_rows = conn.execute(
            sa.select(inventory).order_by(
                inventory.c.broker_account_id,
                inventory.c.asset_id,
            )
        ).mappings().all()
        seen_inventory: set[tuple[str, str]] = set()

        for row in inventory_rows:
            broker_id = str(row["broker_account_id"])
            asset_id = str(row["asset_id"])
            key = (broker_id, asset_id)
            expected_qty = expected_inventory_qty.get(key)
            if expected_qty is None:
                raise RuntimeError(
                    f"orphan sleeve inventory without active cash trade: "
                    f"{broker_id}/{asset_id}"
                )
            actual_qty = float(row["inventory_qty"])
            if abs(actual_qty - expected_qty) > 1e-9:
                raise RuntimeError(
                    f"cash inventory quantity drift for {broker_id}/{asset_id}"
                )

            observation = require_observation(asset_id)
            inventory_mtm[broker_id] += inventory_market_value_usd(
                quantity=actual_qty,
                conservative_bid=float(observation.bid),
            )
            seen_inventory.add(key)

        missing_inventory = set(expected_inventory_qty) - seen_inventory
        if missing_inventory:
            broker_id, asset_id = sorted(missing_inventory)[0]
            raise RuntimeError(
                f"active cash trade missing sleeve inventory: "
                f"{broker_id}/{asset_id}"
            )

        projections: list[SleeveEquityProjection] = []
        for broker_id, ledger in sorted(ledger_rows.items()):
            projections.append(
                sleeve_equity_projection(
                    broker_account_id=broker_id,
                    cash_available_usd=float(ledger["cash_available_usd"]),
                    cash_reserved_usd=float(ledger["cash_reserved_usd"]),
                    cash_inventory_backing_reserve_usd=inventory_backing[
                        broker_id
                    ],
                    inventory_mtm_usd=inventory_mtm[broker_id],
                    non_inventory_unrealized_pnl_usd=(
                        non_inventory_unrealized[broker_id]
                    ),
                    fees_accrued_usd=float(ledger["fees_accrued_usd"]),
                )
            )

        return firm_equity_projection(projections)

    def project_open_risk(
        self,
        conn: Connection,
        *,
        cluster_by_asset: Mapping[str, str],
    ) -> BookRiskSnapshot:
        """Project conservative open stop-risk from the durable active book.

        Cluster identity is supplied explicitly because vNext does not yet have a
        frozen twelve-asset cluster assignment. Historical legacy cluster labels
        are not imported as design authority.

        Until a later management phase persists ratcheted protective-stop state,
        the frozen opening hard stop is the durable stop-risk reference. Because
        the exit contract forbids loosening a trailing stop, this is conservative:
        it may overstate later reduced risk but must not understate opening risk.
        """
        active_positions = self.tables["active_positions"]
        trades = self.tables["open_trades"]

        rows: list[BookRiskPosition] = []
        active_rows = conn.execute(
            sa.select(active_positions).order_by(active_positions.c.position_key)
        ).mappings().all()

        for active in active_rows:
            trade = conn.execute(
                sa.select(trades).where(
                    trades.c.trade_id == active["trade_id"]
                )
            ).mappings().first()
            if trade is None:
                raise RuntimeError(
                    f"active position missing OpenTrade: {active['position_key']}"
                )

            position_key = str(active["position_key"])
            asset_id = str(active["asset_id"])
            if str(trade["position_key"]) != position_key:
                raise RuntimeError(
                    f"active/OpenTrade position_key drift: {position_key}"
                )
            if str(trade["asset_id"]) != asset_id:
                raise RuntimeError(
                    f"active/OpenTrade asset drift: {position_key}"
                )
            if str(trade["side"]) != str(active["side"]):
                raise RuntimeError(
                    f"active/OpenTrade side drift: {position_key}"
                )
            if abs(float(trade["quantity"]) - float(active["quantity"])) > 1e-12:
                raise RuntimeError(
                    f"active/OpenTrade quantity drift: {position_key}"
                )

            cluster_value = cluster_by_asset.get(asset_id)
            cluster_id = (
                str(cluster_value).strip()
                if cluster_value is not None
                else ""
            )
            if not cluster_id:
                raise ValueError(
                    f"missing canonical cluster assignment for active asset: {asset_id}"
                )

            exit_payload = dict(trade["exit_plan_payload"] or {})
            hard_stop = exit_payload.get("hard_stop_price")
            if hard_stop is None:
                raise RuntimeError(
                    f"active trade missing frozen hard stop: {trade['trade_id']}"
                )

            try:
                computed_risk = stop_risk_usd(
                    registry_row(asset_id),
                    side=str(trade["side"]),
                    quantity=float(trade["quantity"]),
                    entry_price=float(trade["avg_entry_price"]),
                    stop_price=float(hard_stop),
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"invalid active stop-risk geometry: {trade['trade_id']}"
                ) from exc

            stored_risk = float(trade["initial_stop_risk_usd"])
            tolerance = max(1e-6, computed_risk * 1e-9)
            if abs(stored_risk - computed_risk) > tolerance:
                raise RuntimeError(
                    f"initial stop-risk drift for trade: {trade['trade_id']}"
                )

            rows.append(
                BookRiskPosition(
                    trade_id=str(trade["trade_id"]),
                    position_key=position_key,
                    asset_id=asset_id,
                    cluster_id=cluster_id,
                    stop_risk_usd=computed_risk,
                )
            )

        return aggregate_book_risk(rows)

    def event_rows(self, conn: Connection) -> list[dict[str, Any]]:
        table = self.tables["event_ledger"]
        rows = conn.execute(
            sa.select(table).order_by(table.c.created_at_utc, table.c.event_id)
        ).mappings()
        return [dict(row) for row in rows]
