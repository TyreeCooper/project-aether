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
import math
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import (
    CalendarState,
    Lineage,
    MarketObservation,
    OrderIntent,
    OrderIntentState,
    QualityState,
    ReviewCard,
    SessionState,
    Setup,
    SetupState,
    Ticket,
    TicketState,
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
from aether_vnext.execution import entry_fill_price
from aether_vnext.evidence import CostSensitivity, ProfitabilityEvidence
from aether_vnext.freeze import EvidenceState
from aether_vnext.registry import ProductType, registry_row
from aether_vnext.reservations import reservation_requirement
from aether_vnext.risk import (
    BookRiskPosition,
    BookRiskSnapshot,
    RiskExposure,
    aggregate_book_risk,
    risk_limits_usd,
    size_candidate_to_risk,
    stop_risk_usd,
)
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.review import (
    ReviewGateInput,
    assess_review_gates,
    validate_review_verdict,
)
from aether_vnext.schema import build_metadata
from aether_vnext.playbook_exits import exit_rule
from aether_vnext.playbooks import (
    SEED_ASSET_CLUSTERS,
    asset_risk_hitches,
    cluster_for_asset,
    playbook,
)
from aether_vnext.seed_truth import ASSET_BROKER_ACCOUNT
from aether_vnext.sniper import SniperDecision, signal_key_for_setup


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

    def record_watch_setup(
        self,
        conn: Connection,
        setup: Setup,
    ) -> None:
        """Persist one source-bound Scout WATCH claim and its forensic lineage.

        This is insert-only. The database unique key enforces one evaluation for
        one playbook/asset/horizon/side on one completed trigger bar.
        """
        if setup.state is not SetupState.WATCH:
            raise ValueError("Scout persistence accepts WATCH setups only")
        if setup.trigger_bar_close_exchange_ts is None:
            raise ValueError("trigger_bar_close_exchange_ts is required")
        if setup.trigger_bar_close_exchange_ts.tzinfo is None:
            raise ValueError("trigger_bar_close_exchange_ts must be timezone-aware")

        lineage = setup.lineage
        if not lineage.firm_event_id:
            raise ValueError("firm_event_id is required")
        if lineage.setup_id != setup.setup_id:
            raise ValueError("lineage setup_id mismatch")
        if not lineage.playbook_id or not lineage.playbook_version:
            raise ValueError("playbook identity is required")
        if not lineage.risk_cluster_id:
            raise ValueError("risk_cluster_id is required")

        spec = playbook(lineage.playbook_id)
        if not spec.scout_definition_enabled:
            raise ValueError("playbook is not operationally Scout-enabled")
        if spec.version != lineage.playbook_version:
            raise ValueError("playbook_version mismatch")
        if lineage.asset_id not in spec.allowed_assets:
            raise ValueError("asset violates playbook contract")
        if setup.side not in spec.allowed_sides:
            raise ValueError("side violates playbook contract")
        if setup.horizon != spec.horizon:
            raise ValueError("horizon violates playbook contract")

        expected_route = f"{lineage.asset_id}:{setup.horizon}:{setup.side}"
        if lineage.route_id != expected_route:
            raise ValueError("canonical route_id mismatch")

        expected_cluster = cluster_for_asset(lineage.asset_id)
        if lineage.risk_cluster_id != expected_cluster:
            raise ValueError("canonical risk_cluster_id mismatch")

        expected_hitches = {
            str(asset_id): float(fraction)
            for asset_id, fraction in asset_risk_hitches(
                lineage.playbook_id
            ).items()
        }
        actual_hitches = {
            str(asset_id): float(fraction)
            for asset_id, fraction in lineage.asset_risk_hitches.items()
        }
        if actual_hitches != expected_hitches:
            raise ValueError("canonical asset_risk_hitches mismatch")

        bound_exit = exit_rule(lineage.playbook_id)
        if setup.exit_contract_complete is None:
            raise ValueError("exit_contract_complete is required")
        if bool(setup.exit_contract_complete) != bound_exit.source_complete:
            raise ValueError("exit-contract completeness mismatch")
        if setup.exit_contract_gap != bound_exit.unresolved_reason:
            raise ValueError("exit-contract gap mismatch")

        observations = self.tables["market_observations"]
        observation = conn.execute(
            sa.select(observations).where(
                observations.c.observation_id
                == lineage.market_observation_id
            )
        ).mappings().first()
        if observation is None:
            raise KeyError(
                f"unknown market observation: {lineage.market_observation_id}"
            )
        if str(observation["asset_id"]) != lineage.asset_id:
            raise ValueError("market observation asset mismatch")

        lineage_table = self.tables["decision_lineage"]
        setup_table = self.tables["setups"]

        conn.execute(
            lineage_table.insert().values(
                firm_event_id=lineage.firm_event_id,
                setup_id=setup.setup_id,
                ticket_id=None,
                order_intent_id=None,
                trade_id=None,
                asset_id=lineage.asset_id,
                route_id=lineage.route_id,
                playbook_id=lineage.playbook_id,
                playbook_version=lineage.playbook_version,
                risk_cluster_id=lineage.risk_cluster_id,
                asset_risk_hitches=actual_hitches,
                policy_version=lineage.policy_version,
                configuration_hash=lineage.configuration_hash,
                market_observation_id=lineage.market_observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=lineage.created_at_utc,
                row_version=1,
            )
        )
        conn.execute(
            setup_table.insert().values(
                setup_id=setup.setup_id,
                firm_event_id=lineage.firm_event_id,
                asset_id=lineage.asset_id,
                route_id=lineage.route_id,
                state=setup.state.value,
                side=setup.side,
                horizon=setup.horizon,
                playbook_id=lineage.playbook_id,
                playbook_version=lineage.playbook_version,
                risk_cluster_id=lineage.risk_cluster_id,
                asset_risk_hitches=actual_hitches,
                trigger_bar_close_exchange_ts=(
                    setup.trigger_bar_close_exchange_ts
                ),
                exit_contract_complete=setup.exit_contract_complete,
                exit_contract_gap=setup.exit_contract_gap,
                invalidation=setup.invalidation,
                quality=setup.quality,
                intel_pack=dict(setup.intel_pack),
                policy_version=lineage.policy_version,
                configuration_hash=lineage.configuration_hash,
                market_observation_id=lineage.market_observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=lineage.created_at_utc,
            )
        )

    def load_setup(
        self,
        conn: Connection,
        *,
        setup_id: str,
    ) -> Setup | None:
        setups = self.tables["setups"]
        lineage_table = self.tables["decision_lineage"]
        row = conn.execute(
            sa.select(setups, lineage_table)
            .join(
                lineage_table,
                lineage_table.c.firm_event_id
                == setups.c.firm_event_id,
            )
            .where(setups.c.setup_id == setup_id)
        ).mappings().first()
        if row is None:
            return None
        return Setup(
            setup_id=str(row["setup_id"]),
            lineage=Lineage(
                asset_id=str(row["asset_id"]),
                route_id=str(row["route_id"]),
                policy_version=str(row["policy_version"]),
                configuration_hash=str(row["configuration_hash"]),
                market_observation_id=str(row["market_observation_id"]),
                created_at_utc=_stored_utc(row["created_at_utc"]),
                firm_event_id=str(row["firm_event_id"]),
                setup_id=str(row["setup_id"]),
                playbook_id=str(row["playbook_id"]),
                playbook_version=str(row["playbook_version"]),
                risk_cluster_id=str(row["risk_cluster_id"]),
                asset_risk_hitches={
                    str(k): float(v)
                    for k, v in dict(
                        row["asset_risk_hitches"] or {}
                    ).items()
                },
            ),
            state=SetupState(str(row["state"])),
            side=str(row["side"]),
            horizon=str(row["horizon"]),
            invalidation=row["invalidation"],
            quality=row["quality"],
            intel_pack=dict(row["intel_pack"] or {}),
            trigger_bar_close_exchange_ts=_stored_utc(
                row["trigger_bar_close_exchange_ts"]
            ),
            exit_contract_complete=bool(
                row["exit_contract_complete"]
            ),
            exit_contract_gap=row["exit_contract_gap"],
        )

    def record_sniper_ticket(
        self,
        conn: Connection,
        *,
        setup_id: str,
        ticket_id: str,
        decision: SniperDecision,
        market_observation_id: str,
        created_at_utc: datetime,
        desk_scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist Sniper FIRE or canonical rejection without sizing the ticket."""
        if created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")

        setups = self.tables["setups"]
        tickets = self.tables["tickets"]
        lineage_table = self.tables["decision_lineage"]
        observations = self.tables["market_observations"]
        review_state = self.tables["route_review_state"]

        setup_row = conn.execute(
            sa.select(setups)
            .where(setups.c.setup_id == setup_id)
            .with_for_update()
        ).mappings().first()
        if setup_row is None:
            raise KeyError(f"unknown setup: {setup_id}")

        lineage_row = conn.execute(
            sa.select(lineage_table)
            .where(
                lineage_table.c.firm_event_id
                == setup_row["firm_event_id"]
            )
            .with_for_update()
        ).mappings().one()

        if setup_row["exit_contract_complete"] is not True:
            raise ValueError(
                "incomplete playbook ExitPlan contract cannot create Ticket"
            )

        observation = conn.execute(
            sa.select(observations).where(
                observations.c.observation_id
                == market_observation_id
            )
        ).mappings().first()
        if observation is None:
            raise KeyError(
                f"unknown market observation: {market_observation_id}"
            )
        if observation["asset_id"] != setup_row["asset_id"]:
            raise ValueError("market observation asset mismatch")

        expected_signal = signal_key_for_setup(self.load_setup(
            conn, setup_id=setup_id
        ))
        if decision.signal_key != expected_signal:
            raise ValueError("Sniper signal_key mismatch")

        duplicate = conn.execute(
            sa.select(tickets.c.ticket_id).where(
                tickets.c.signal_key == decision.signal_key
            )
        ).first()
        if duplicate is not None:
            conn.execute(
                setups.update()
                .where(setups.c.setup_id == setup_id)
                .values(
                    first_killed_by="Sniper",
                    first_kill_reason=ReasonCode.SIGNAL_KEY_DUPLICATE.value,
                )
            )
            conn.execute(
                lineage_table.update()
                .where(
                    lineage_table.c.firm_event_id
                    == setup_row["firm_event_id"]
                )
                .values(
                    first_killed_by="Sniper",
                    first_kill_reason=ReasonCode.SIGNAL_KEY_DUPLICATE.value,
                    market_observation_id=market_observation_id,
                    row_version=lineage_table.c.row_version + 1,
                )
            )
            return {
                "ok": False,
                "state": "REJECTED",
                "reject_code": ReasonCode.SIGNAL_KEY_DUPLICATE.value,
                "ticket_created": False,
            }

        reject_code = decision.reject_code

        route_state = conn.execute(
            sa.select(review_state).where(
                review_state.c.route_id == setup_row["route_id"]
            )
        ).mappings().first()
        if route_state is not None and (
            str(route_state["evidence_state"]).upper() == "BENCH"
            or str(route_state["operational_state"]).upper()
            in {"DISABLED", "HALT"}
        ):
            reject_code = ReasonCode.ROUTE_BENCHED.value

        governor_block = self.governor_block_for_admission(
            conn,
            route_id=str(setup_row["route_id"]),
            venue=str(observation["venue"]),
            product_id=str(setup_row["asset_id"]),
            desk_scope_id=desk_scope_id,
        )
        if governor_block is not None:
            reject_code = str(governor_block["reason_code"])

        if str(setup_row["state"]) != SetupState.WATCH.value:
            reject_code = ReasonCode.STALE_SETUP.value

        state = (
            TicketState.FIRE.value
            if decision.fire and reject_code is None
            else TicketState.REJECTED.value
        )
        first_killed_by = None if state == TicketState.FIRE.value else "Sniper"
        first_kill_reason = None if state == TicketState.FIRE.value else reject_code

        conn.execute(
            tickets.insert().values(
                ticket_id=ticket_id,
                exit_plan_id=None,
                setup_id=setup_id,
                firm_event_id=setup_row["firm_event_id"],
                asset_id=setup_row["asset_id"],
                route_id=setup_row["route_id"],
                state=state,
                signal_key=decision.signal_key,
                side=setup_row["side"],
                horizon=setup_row["horizon"],
                stop_price=decision.stop_price,
                quantity=None,
                modeled_round_trip_cost_pct=None,
                reject_code=reject_code,
                policy_version=setup_row["policy_version"],
                configuration_hash=setup_row["configuration_hash"],
                market_observation_id=market_observation_id,
                first_killed_by=first_killed_by,
                first_kill_reason=first_kill_reason,
                created_at_utc=created_at_utc,
            )
        )

        setup_values: dict[str, Any] = {
            "first_killed_by": first_killed_by,
            "first_kill_reason": first_kill_reason,
        }
        if state == TicketState.FIRE.value:
            setup_values["state"] = SetupState.FIRE.value
        conn.execute(
            setups.update()
            .where(setups.c.setup_id == setup_id)
            .values(**setup_values)
        )
        conn.execute(
            lineage_table.update()
            .where(
                lineage_table.c.firm_event_id
                == setup_row["firm_event_id"]
            )
            .values(
                ticket_id=ticket_id,
                market_observation_id=market_observation_id,
                first_killed_by=first_killed_by,
                first_kill_reason=first_kill_reason,
                row_version=lineage_table.c.row_version + 1,
            )
        )
        return {
            "ok": state == TicketState.FIRE.value,
            "state": state,
            "reject_code": reject_code,
            "ticket_created": True,
            "ticket_id": ticket_id,
            "signal_key": decision.signal_key,
        }

    def load_ticket(
        self,
        conn: Connection,
        *,
        ticket_id: str,
    ) -> Ticket | None:
        tickets = self.tables["tickets"]
        lineage_table = self.tables["decision_lineage"]
        row = conn.execute(
            sa.select(tickets).where(tickets.c.ticket_id == ticket_id)
        ).mappings().first()
        if row is None:
            return None
        lineage_row = conn.execute(
            sa.select(lineage_table).where(
                lineage_table.c.firm_event_id == row["firm_event_id"]
            )
        ).mappings().one()
        return Ticket(
            ticket_id=str(row["ticket_id"]),
            lineage=Lineage(
                asset_id=str(row["asset_id"]),
                route_id=str(row["route_id"]),
                policy_version=str(row["policy_version"]),
                configuration_hash=str(row["configuration_hash"]),
                market_observation_id=str(row["market_observation_id"]),
                created_at_utc=_stored_utc(row["created_at_utc"]),
                firm_event_id=str(row["firm_event_id"]),
                setup_id=str(row["setup_id"]),
                ticket_id=str(row["ticket_id"]),
                first_killed_by=row["first_killed_by"],
                first_kill_reason=row["first_kill_reason"],
                playbook_id=lineage_row["playbook_id"],
                playbook_version=lineage_row["playbook_version"],
                risk_cluster_id=lineage_row["risk_cluster_id"],
                asset_risk_hitches={
                    str(k): float(v)
                    for k, v in dict(
                        lineage_row["asset_risk_hitches"] or {}
                    ).items()
                },
            ),
            state=TicketState(str(row["state"])),
            signal_key=str(row["signal_key"]),
            side=str(row["side"]),
            horizon=str(row["horizon"]),
            stop_price=row["stop_price"],
            quantity=row["quantity"],
            modeled_round_trip_cost_pct=row["modeled_round_trip_cost_pct"],
            reject_code=row["reject_code"],
            exit_plan_id=row["exit_plan_id"],
        )

    def size_fire_ticket(
        self,
        conn: Connection,
        *,
        ticket_id: str,
        market_observation_id: str,
        current_observations: Mapping[str, MarketObservation],
        estimated_round_trip_cost_per_unit_usd: float,
        created_at_utc: datetime,
        event_id: str,
        actor: str = "Risk",
        broker_margin_cap_qty: float | None = None,
        firm_capital_cap_qty: float | None = None,
    ) -> dict[str, Any]:
        """Apply Risk authority to exactly one FIRE Ticket.

        Risk writes quantity only. Clerk economics remain unset until SIZE -> READY.
        Portfolio later rechecks the same hard envelope atomically before reservation.
        """
        if created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if float(estimated_round_trip_cost_per_unit_usd) < 0:
            raise ValueError(
                "estimated_round_trip_cost_per_unit_usd cannot be negative"
            )

        tickets = self.tables["tickets"]
        lineage_table = self.tables["decision_lineage"]
        observations = self.tables["market_observations"]

        ticket = conn.execute(
            sa.select(tickets)
            .where(tickets.c.ticket_id == ticket_id)
            .with_for_update()
        ).mappings().first()
        if ticket is None:
            raise KeyError(f"unknown ticket: {ticket_id}")
        if str(ticket["state"]) != TicketState.FIRE.value:
            raise ValueError("Risk sizing requires FIRE ticket")
        if ticket["stop_price"] is None:
            raise ValueError("FIRE ticket requires stop_price")

        lineage = conn.execute(
            sa.select(lineage_table)
            .where(lineage_table.c.firm_event_id == ticket["firm_event_id"])
            .with_for_update()
        ).mappings().first()
        if lineage is None:
            raise RuntimeError("FIRE ticket missing decision lineage")
        if lineage["playbook_id"] is None:
            raise RuntimeError("FIRE ticket missing durable playbook identity")

        asset_id = str(ticket["asset_id"])
        canonical_cluster = cluster_for_asset(asset_id)
        if str(lineage["risk_cluster_id"]) != canonical_cluster:
            raise RuntimeError("FIRE ticket canonical cluster drift")

        hitches = {
            str(target): float(fraction)
            for target, fraction in dict(
                lineage["asset_risk_hitches"] or {}
            ).items()
        }
        expected_hitches = {
            str(target): float(fraction)
            for target, fraction in asset_risk_hitches(
                str(lineage["playbook_id"])
            ).items()
        }
        if hitches != expected_hitches:
            raise RuntimeError("FIRE ticket canonical Risk hitch drift")

        observation_row = conn.execute(
            sa.select(observations).where(
                observations.c.observation_id == market_observation_id
            )
        ).mappings().first()
        if observation_row is None:
            raise KeyError(
                f"unknown market observation: {market_observation_id}"
            )
        if str(observation_row["asset_id"]) != asset_id:
            raise ValueError("Risk market observation asset mismatch")

        observation = MarketObservation(
            observation_id=str(observation_row["observation_id"]),
            asset_id=asset_id,
            venue=str(observation_row["venue"]),
            bid=observation_row["bid"],
            ask=observation_row["ask"],
            last=observation_row["last"],
            mark=observation_row["mark"],
            source=str(observation_row["source"]),
            exchange_ts=(
                _stored_utc(observation_row["exchange_ts"])
                if observation_row["exchange_ts"] is not None
                else None
            ),
            received_ts=_stored_utc(observation_row["received_ts"]),
            age_ms=int(observation_row["age_ms"]),
            spread_abs=observation_row["spread_abs"],
            spread_bps=observation_row["spread_bps"],
            session_state=SessionState(str(observation_row["session_state"])),
            quality_state=QualityState(str(observation_row["quality_state"])),
            fallback_reason=observation_row["fallback_reason"],
            calendar_state=CalendarState(str(observation_row["calendar_state"])),
            data_version=str(observation_row["data_version"]),
        )

        if (
            observation.quality_state is not QualityState.HEALTHY
            or observation.bid is None
            or observation.ask is None
        ):
            reject_code = ReasonCode.MARKET_STALE.value
            result = None
        else:
            entry_price = entry_fill_price(
                observation,
                position_side=str(ticket["side"]),
            )
            firm_equity = self.project_firm_equity(
                conn,
                observations=current_observations,
            )
            if firm_equity.consolidated_equity_usd <= 0:
                raise RuntimeError("Firm equity must be positive for Risk sizing")

            open_snapshot = self.project_open_risk(
                conn,
                cluster_by_asset=SEED_ASSET_CLUSTERS,
            )
            open_exposure = open_snapshot.exposure_for(
                asset_id=asset_id,
                cluster_id=canonical_cluster,
            )
            pending_exposure = self._pending_open_risk_exposure(
                conn,
                asset_id=asset_id,
                cluster_id=canonical_cluster,
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

            limits = risk_limits_usd(
                firm_equity.consolidated_equity_usd
            )
            cross_remaining: dict[str, float] = {}
            for target_asset in hitches:
                target_cluster = cluster_for_asset(target_asset)
                target_open = open_snapshot.exposure_for(
                    asset_id=target_asset,
                    cluster_id=target_cluster,
                )
                target_pending = self._pending_open_risk_exposure(
                    conn,
                    asset_id=target_asset,
                    cluster_id=target_cluster,
                )
                occupied = (
                    target_open.asset_open_risk_usd
                    + target_pending.asset_open_risk_usd
                )
                cross_remaining[target_asset] = max(
                    limits.asset_usd - occupied,
                    0.0,
                )

            result = size_candidate_to_risk(
                registry_row(asset_id),
                side=str(ticket["side"]),
                entry_price=entry_price,
                stop_price=float(ticket["stop_price"]),
                equity_usd=firm_equity.consolidated_equity_usd,
                exposure=exposure,
                broker_margin_cap_qty=broker_margin_cap_qty,
                firm_capital_cap_qty=firm_capital_cap_qty,
                estimated_round_trip_cost_per_unit_usd=(
                    estimated_round_trip_cost_per_unit_usd
                ),
                asset_risk_hitches=hitches,
                cross_asset_remaining_risk_usd=cross_remaining,
            )
            reject_code = result.reject_code

        if result is None or not result.ok:
            reject = str(reject_code)
            conn.execute(
                tickets.update()
                .where(tickets.c.ticket_id == ticket_id)
                .values(
                    state=TicketState.REJECTED.value,
                    quantity=None,
                    reject_code=reject,
                    market_observation_id=market_observation_id,
                    first_killed_by="Risk",
                    first_kill_reason=reject,
                )
            )
            conn.execute(
                lineage_table.update()
                .where(
                    lineage_table.c.firm_event_id == ticket["firm_event_id"]
                )
                .values(
                    market_observation_id=market_observation_id,
                    first_killed_by="Risk",
                    first_kill_reason=reject,
                    row_version=lineage_table.c.row_version + 1,
                )
            )
            self.append_event(
                conn,
                event_id=event_id,
                aggregate_type="ticket",
                aggregate_id=ticket_id,
                prior_state=TicketState.FIRE.value,
                new_state=TicketState.REJECTED.value,
                seat="Risk",
                reason_code=reject,
                policy_version=str(ticket["policy_version"]),
                configuration_hash=str(ticket["configuration_hash"]),
                market_observation_id=market_observation_id,
                actor=actor,
                created_at_utc=created_at_utc,
                payload={},
            )
            return {
                "ok": False,
                "state": TicketState.REJECTED.value,
                "reject_code": reject,
            }

        conn.execute(
            tickets.update()
            .where(tickets.c.ticket_id == ticket_id)
            .values(
                state=TicketState.SIZE.value,
                quantity=result.quantity,
                modeled_round_trip_cost_pct=None,
                reject_code=None,
                market_observation_id=market_observation_id,
            )
        )
        conn.execute(
            lineage_table.update()
            .where(lineage_table.c.firm_event_id == ticket["firm_event_id"])
            .values(
                market_observation_id=market_observation_id,
                row_version=lineage_table.c.row_version + 1,
            )
        )
        self.append_event(
            conn,
            event_id=event_id,
            aggregate_type="ticket",
            aggregate_id=ticket_id,
            prior_state=TicketState.FIRE.value,
            new_state=TicketState.SIZE.value,
            seat="Risk",
            reason_code="risk.size",
            policy_version=str(ticket["policy_version"]),
            configuration_hash=str(ticket["configuration_hash"]),
            market_observation_id=market_observation_id,
            actor=actor,
            created_at_utc=created_at_utc,
            payload={
                "quantity": result.quantity,
                "stop_risk_usd": result.stop_risk_usd,
                "estimated_round_trip_cost_usd": (
                    result.estimated_round_trip_cost_usd
                ),
                "modeled_loss_at_stop_usd": result.modeled_loss_at_stop_usd,
                "risk_cluster_id": canonical_cluster,
                "asset_risk_hitches_usd": dict(
                    result.asset_risk_hitches_usd
                ),
            },
        )
        return {
            "ok": True,
            "state": TicketState.SIZE.value,
            "quantity": result.quantity,
            "stop_risk_usd": result.stop_risk_usd,
            "estimated_round_trip_cost_usd": (
                result.estimated_round_trip_cost_usd
            ),
            "modeled_loss_at_stop_usd": result.modeled_loss_at_stop_usd,
            "asset_risk_hitches_usd": dict(
                result.asset_risk_hitches_usd
            ),
        }

    def record_profitability_review(
        self,
        conn: Connection,
        *,
        evidence: ProfitabilityEvidence,
        review_card: ReviewCard,
        gate_input: ReviewGateInput,
    ) -> ReviewCard:
        """Persist immutable evidence plus Review's forward evidence-state decision.

        Review owns evidence/review state only. This transaction does not mutate
        cash, margin, positions, orders, tickets, or execution state.
        """
        if review_card.as_of_utc.tzinfo is None:
            raise ValueError("ReviewCard as_of_utc must be timezone-aware")
        if review_card.evidence_id != evidence.evidence_id:
            raise ValueError("ReviewCard evidence_id mismatch")
        if review_card.route_id != evidence.route_id:
            raise ValueError("ReviewCard route_id mismatch")
        if review_card.playbook_id != evidence.playbook_id:
            raise ValueError("ReviewCard playbook_id mismatch")
        if review_card.playbook_version != evidence.playbook_version:
            raise ValueError("ReviewCard playbook_version mismatch")
        if review_card.configuration_hash != evidence.configuration_hash:
            raise ValueError("ReviewCard configuration_hash mismatch")
        if review_card.reviewer != evidence.reviewer:
            raise ValueError("ReviewCard reviewer mismatch")

        try:
            target_state = EvidenceState(str(review_card.evidence_state))
        except ValueError as exc:
            raise ValueError("unknown Review evidence_state") from exc
        if str(evidence.verdict) != target_state.value:
            raise ValueError("evidence verdict must equal Review evidence_state")

        if gate_input.evidence_id != evidence.evidence_id:
            raise ValueError("Review gate evidence_id mismatch")
        if int(gate_input.n_closed) != int(evidence.n_trades):
            raise ValueError("Review gate n_closed mismatch")
        if not math.isclose(
            float(gate_input.net_expectancy_after_costs),
            float(evidence.net_expectancy_usd),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Review gate expectancy mismatch")
        if not math.isclose(
            float(gate_input.profit_factor),
            float(evidence.profit_factor),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Review gate profit_factor mismatch")
        if not math.isclose(
            float(gate_input.stop_rate),
            float(evidence.stop_rate),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Review gate stop_rate mismatch")
        if len(gate_input.fold_expectancy_after_plus25_cost) != len(
            evidence.oos_windows
        ):
            raise ValueError("Review gate fold count mismatch")

        assessment = assess_review_gates(gate_input)
        validate_review_verdict(assessment, target_state)

        spec = playbook(evidence.playbook_id)
        if spec.version != evidence.playbook_version:
            raise ValueError("playbook_version mismatch")

        policies = self.tables["policy_snapshots"]
        policy = conn.execute(
            sa.select(policies).where(
                policies.c.configuration_hash
                == evidence.configuration_hash
            )
        ).mappings().first()
        if policy is None:
            raise KeyError(
                f"unknown configuration_hash: {evidence.configuration_hash}"
            )
        if str(policy["policy_version"]) != evidence.policy_version:
            raise ValueError("policy_version/configuration_hash mismatch")

        evidence_table = self.tables["profitability_evidence"]
        review_table = self.tables["review_cards"]
        route_state = self.tables["route_review_state"]

        conn.execute(
            evidence_table.insert().values(
                evidence_id=evidence.evidence_id,
                route_id=evidence.route_id,
                playbook_id=evidence.playbook_id,
                playbook_version=evidence.playbook_version,
                policy_version=evidence.policy_version,
                configuration_hash=evidence.configuration_hash,
                data_version=evidence.data_version,
                fill_model_version=evidence.fill_model_version,
                fee_schedule_version=evidence.fee_schedule_version,
                in_sample_window=evidence.in_sample_window,
                oos_windows=list(evidence.oos_windows),
                n_trades=evidence.n_trades,
                net_expectancy_usd=evidence.net_expectancy_usd,
                profit_factor=evidence.profit_factor,
                win_rate=evidence.win_rate,
                avg_win_usd=evidence.avg_win_usd,
                avg_loss_usd=evidence.avg_loss_usd,
                stop_rate=evidence.stop_rate,
                max_drawdown_usd=evidence.max_drawdown_usd,
                max_drawdown_pct=evidence.max_drawdown_pct,
                median_duration_s=evidence.median_duration_s,
                capture_efficiency=evidence.capture_efficiency,
                cost_sensitivity={
                    "base": dict(evidence.cost_sensitivity.base),
                    "plus25": dict(evidence.cost_sensitivity.plus25),
                    "plus50": dict(evidence.cost_sensitivity.plus50),
                },
                regime_matrix=dict(evidence.regime_matrix),
                benchmark_result=dict(evidence.benchmark_result),
                capacity_result=dict(evidence.capacity_result),
                portfolio_contribution=dict(
                    evidence.portfolio_contribution
                ),
                model_risks=list(evidence.model_risks),
                verdict=evidence.verdict,
                reviewer=evidence.reviewer,
                as_of_utc=evidence.as_of_utc,
            )
        )
        conn.execute(
            review_table.insert().values(
                review_card_id=review_card.review_card_id,
                firm_event_id=None,
                trade_id=None,
                route_id=review_card.route_id,
                playbook_id=review_card.playbook_id,
                playbook_version=review_card.playbook_version,
                as_of_utc=review_card.as_of_utc,
                evidence_state=target_state.value,
                evidence_id=evidence.evidence_id,
                decision_reason=review_card.decision_reason,
                reviewer=review_card.reviewer,
                configuration_hash=review_card.configuration_hash,
            )
        )

        current = conn.execute(
            sa.select(route_state)
            .where(route_state.c.route_id == review_card.route_id)
            .with_for_update()
        ).mappings().first()
        if current is None:
            conn.execute(
                route_state.insert().values(
                    route_id=review_card.route_id,
                    evidence_state=target_state.value,
                    operational_state=spec.operational_state.value,
                    review_card_id=review_card.review_card_id,
                    updated_at_utc=review_card.as_of_utc,
                    row_version=1,
                )
            )
        else:
            conn.execute(
                route_state.update()
                .where(
                    route_state.c.route_id == review_card.route_id,
                    route_state.c.row_version == current["row_version"],
                )
                .values(
                    evidence_state=target_state.value,
                    review_card_id=review_card.review_card_id,
                    updated_at_utc=review_card.as_of_utc,
                    row_version=route_state.c.row_version + 1,
                )
            )

        return review_card

    def load_profitability_evidence(
        self,
        conn: Connection,
        *,
        evidence_id: str,
    ) -> ProfitabilityEvidence | None:
        table = self.tables["profitability_evidence"]
        row = conn.execute(
            sa.select(table).where(table.c.evidence_id == evidence_id)
        ).mappings().first()
        if row is None:
            return None
        costs = dict(row["cost_sensitivity"] or {})
        return ProfitabilityEvidence(
            evidence_id=str(row["evidence_id"]),
            route_id=str(row["route_id"]),
            playbook_id=str(row["playbook_id"]),
            playbook_version=str(row["playbook_version"]),
            policy_version=str(row["policy_version"]),
            configuration_hash=str(row["configuration_hash"]),
            data_version=str(row["data_version"]),
            fill_model_version=str(row["fill_model_version"]),
            fee_schedule_version=str(row["fee_schedule_version"]),
            in_sample_window=(
                dict(row["in_sample_window"])
                if row["in_sample_window"] is not None
                else None
            ),
            oos_windows=tuple(
                dict(item) for item in (row["oos_windows"] or [])
            ),
            n_trades=int(row["n_trades"]),
            net_expectancy_usd=float(row["net_expectancy_usd"]),
            profit_factor=float(row["profit_factor"]),
            win_rate=float(row["win_rate"]),
            avg_win_usd=float(row["avg_win_usd"]),
            avg_loss_usd=float(row["avg_loss_usd"]),
            stop_rate=float(row["stop_rate"]),
            max_drawdown_usd=float(row["max_drawdown_usd"]),
            max_drawdown_pct=float(row["max_drawdown_pct"]),
            median_duration_s=float(row["median_duration_s"]),
            capture_efficiency=float(row["capture_efficiency"]),
            cost_sensitivity=CostSensitivity(
                base=dict(costs.get("base") or {}),
                plus25=dict(costs.get("plus25") or {}),
                plus50=dict(costs.get("plus50") or {}),
            ),
            regime_matrix=dict(row["regime_matrix"] or {}),
            benchmark_result=dict(row["benchmark_result"] or {}),
            capacity_result=dict(row["capacity_result"] or {}),
            portfolio_contribution=dict(
                row["portfolio_contribution"] or {}
            ),
            model_risks=tuple(
                str(item) for item in (row["model_risks"] or [])
            ),
            verdict=str(row["verdict"]),
            reviewer=str(row["reviewer"]),
            as_of_utc=_stored_utc(row["as_of_utc"]),
        )

    def load_review_card(
        self,
        conn: Connection,
        *,
        review_card_id: str,
    ) -> ReviewCard | None:
        table = self.tables["review_cards"]
        row = conn.execute(
            sa.select(table).where(
                table.c.review_card_id == review_card_id
            )
        ).mappings().first()
        if row is None:
            return None
        return ReviewCard(
            review_card_id=str(row["review_card_id"]),
            route_id=str(row["route_id"]),
            playbook_id=str(row["playbook_id"]),
            playbook_version=str(row["playbook_version"]),
            as_of_utc=_stored_utc(row["as_of_utc"]),
            evidence_state=str(row["evidence_state"]),
            evidence_id=row["evidence_id"],
            decision_reason=str(row["decision_reason"]),
            reviewer=str(row["reviewer"]),
            configuration_hash=str(row["configuration_hash"]),
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

    def _lock_firm_risk_admission_guard(
        self,
        conn: Connection,
    ) -> Mapping[str, Any]:
        guard_table = self.tables["risk_admission_guard"]
        guard = conn.execute(
            sa.select(guard_table)
            .where(guard_table.c.scope_key == "firm")
            .with_for_update()
        ).mappings().first()
        if guard is None:
            raise RuntimeError("Firm risk admission guard is not provisioned")
        return guard

    def risk_admission_reconciliation_issues(
        self,
        conn: Connection,
    ) -> tuple[str, ...]:
        """Return deterministic, read-only findings for Phase-6 risk state."""
        guard_table = self.tables["risk_admission_guard"]
        intents = self.tables["order_intents"]
        reservations = self.tables["risk_admission_reservations"]

        issues: list[str] = []
        guards = conn.execute(
            sa.select(guard_table).order_by(guard_table.c.scope_key)
        ).mappings().all()
        firm_guards = [
            row for row in guards if str(row["scope_key"]) == "firm"
        ]
        if len(firm_guards) != 1:
            issues.append(
                f"firm_risk_guard_count:{len(firm_guards)}"
            )

        intent_rows = {
            str(row["order_intent_id"]): row
            for row in conn.execute(sa.select(intents)).mappings()
        }
        reservation_rows = {
            str(row["order_intent_id"]): row
            for row in conn.execute(sa.select(reservations)).mappings()
        }

        for intent_id, intent in sorted(intent_rows.items()):
            is_pending_open = (
                str(intent["intent_kind"]) == "OPEN"
                and str(intent["state"]) in {"RESERVED", "SUBMITTED"}
            )
            reservation = reservation_rows.get(intent_id)
            if is_pending_open and reservation is None:
                issues.append(
                    f"missing_pending_risk_reservation:{intent_id}"
                )
            if (
                not is_pending_open
                and reservation is not None
            ):
                issues.append(
                    f"risk_reservation_on_nonpending_intent:{intent_id}"
                )

        for intent_id, reservation in sorted(reservation_rows.items()):
            intent = intent_rows.get(intent_id)
            if intent is None:
                issues.append(f"orphan_risk_reservation:{intent_id}")
                continue
            if str(reservation["asset_id"]) != str(intent["asset_id"]):
                issues.append(
                    f"risk_reservation_asset_mismatch:{intent_id}"
                )
            if (
                str(reservation["policy_version"])
                != str(intent["policy_version"])
            ):
                issues.append(
                    f"risk_reservation_policy_mismatch:{intent_id}"
                )
            if (
                str(reservation["configuration_hash"])
                != str(intent["configuration_hash"])
            ):
                issues.append(
                    f"risk_reservation_configuration_mismatch:{intent_id}"
                )
            if not str(reservation["cluster_id"]).strip():
                issues.append(
                    f"risk_reservation_cluster_blank:{intent_id}"
                )
            if float(reservation["stop_risk_usd"]) <= 0:
                issues.append(
                    f"risk_reservation_nonpositive:{intent_id}"
                )
            firm_event_id = intent["firm_event_id"]
            if firm_event_id is not None:
                lineage_row = conn.execute(
                    sa.select(self.tables["decision_lineage"]).where(
                        self.tables["decision_lineage"].c.firm_event_id
                        == firm_event_id
                    )
                ).mappings().first()
                if lineage_row is None:
                    issues.append(
                        f"risk_reservation_lineage_missing:{intent_id}"
                    )
                elif lineage_row["playbook_id"] is not None:
                    actual_hitches = {
                        str(target): float(fraction)
                        for target, fraction in dict(
                            lineage_row["asset_risk_hitches"] or {}
                        ).items()
                    }
                    expected_hitches = {
                        str(target): float(fraction)
                        for target, fraction in asset_risk_hitches(
                            str(lineage_row["playbook_id"])
                        ).items()
                    }
                    if actual_hitches != expected_hitches:
                        issues.append(
                            f"risk_reservation_hitch_mismatch:{intent_id}"
                        )

        return tuple(sorted(set(issues)))

    def _pending_open_risk_exposure(
        self,
        conn: Connection,
        *,
        asset_id: str,
        cluster_id: str,
    ) -> RiskExposure:
        intents = self.tables["order_intents"]
        reservations = self.tables["risk_admission_reservations"]
        lineage = self.tables["decision_lineage"]

        rows = conn.execute(
            sa.select(
                intents.c.order_intent_id,
                intents.c.firm_event_id,
                reservations.c.asset_id,
                reservations.c.cluster_id,
                reservations.c.stop_risk_usd,
                lineage.c.playbook_id,
                lineage.c.asset_risk_hitches,
            )
            .select_from(
                intents.outerjoin(
                    reservations,
                    reservations.c.order_intent_id
                    == intents.c.order_intent_id,
                ).outerjoin(
                    lineage,
                    lineage.c.firm_event_id == intents.c.firm_event_id,
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

            playbook_id = row["playbook_id"]
            hitches = {
                str(target): float(fraction)
                for target, fraction in dict(
                    row["asset_risk_hitches"] or {}
                ).items()
            }
            if playbook_id is not None:
                expected_hitches = {
                    str(target): float(fraction)
                    for target, fraction in asset_risk_hitches(
                        str(playbook_id)
                    ).items()
                }
                if hitches != expected_hitches:
                    raise RuntimeError(
                        "pending OPEN playbook Risk hitch drift: "
                        f"{row['order_intent_id']}"
                    )
            for target_asset, fraction in hitches.items():
                if target_asset == asset_id:
                    asset_risk += risk * fraction

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
        guard = self._lock_firm_risk_admission_guard(conn)

        tickets = self.tables["tickets"]
        observations = self.tables["market_observations"]
        ticket = conn.execute(
            sa.select(tickets).where(tickets.c.ticket_id == ticket_id)
        ).mappings().first()

        candidate_hitches: dict[str, float] = {}
        if ticket is not None and ticket["firm_event_id"] is not None:
            candidate_lineage = conn.execute(
                sa.select(self.tables["decision_lineage"]).where(
                    self.tables["decision_lineage"].c.firm_event_id
                    == ticket["firm_event_id"]
                )
            ).mappings().first()
            if candidate_lineage is None:
                raise RuntimeError("READY ticket missing decision lineage")
            candidate_hitches = {
                str(target): float(fraction)
                for target, fraction in dict(
                    candidate_lineage["asset_risk_hitches"] or {}
                ).items()
            }
            candidate_playbook = candidate_lineage["playbook_id"]
            if candidate_playbook is not None:
                expected_candidate_hitches = {
                    str(target): float(fraction)
                    for target, fraction in asset_risk_hitches(
                        str(candidate_playbook)
                    ).items()
                }
                if candidate_hitches != expected_candidate_hitches:
                    raise RuntimeError(
                        "READY ticket playbook Risk hitch drift"
                    )

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
            return self._reserve_order_intent_after_admission(
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
            for target_asset, fraction in sorted(
                candidate_hitches.items()
            ):
                target_cluster = cluster_for_asset(target_asset)
                target_open = open_snapshot.exposure_for(
                    asset_id=target_asset,
                    cluster_id=target_cluster,
                )
                target_pending = self._pending_open_risk_exposure(
                    conn,
                    asset_id=target_asset,
                    cluster_id=target_cluster,
                )
                target_occupied = (
                    target_open.asset_open_risk_usd
                    + target_pending.asset_open_risk_usd
                )
                if (
                    target_occupied + candidate_risk * fraction
                    > limits.asset_usd + epsilon
                ):
                    reason_code = "asset_risk_full"
                    break

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

        result = self._reserve_order_intent_after_admission(
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

    def _reserve_order_intent_after_admission(
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

        """Low-level persistence primitive after admission checks.

        Runtime OPEN callers must use reserve_risk_checked_open_intent(). This
        method remains private so execution-contract unit tests can exercise
        reservation mechanics without constructing the entire Risk/Governor
        pipeline.
        """
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
        risk_reservations = self.tables["risk_admission_reservations"]

        # Serialize the pending-risk -> OpenTrade source transition against
        # every new Phase-A admission. This closes the READ COMMITTED gap where
        # an admission could otherwise observe neither source during a fill.
        self._lock_firm_risk_admission_guard(conn)

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

        if intent["intent_kind"] != "OPEN":
            return {
                "ok": False,
                "error": "illegal_intent_kind",
                "state": intent["state"],
            }

        risk_reservation = conn.execute(
            sa.select(risk_reservations)
            .where(
                risk_reservations.c.order_intent_id == order_intent_id
            )
            .with_for_update()
        ).mappings().first()
        if (
            risk_reservation is not None
            and str(risk_reservation["asset_id"]) != str(intent["asset_id"])
        ):
            raise RuntimeError(
                f"risk reservation asset drift: {order_intent_id}"
            )

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

        pending_stop_risk_usd = (
            float(risk_reservation["stop_risk_usd"])
            if risk_reservation is not None
            else None
        )
        if risk_reservation is not None:
            conn.execute(
                risk_reservations.delete().where(
                    risk_reservations.c.order_intent_id
                    == order_intent_id
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
                "pending_stop_risk_released_usd": pending_stop_risk_usd,
                "risk_source_after_fill": "open_trade",
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
        risk_reservations = self.tables["risk_admission_reservations"]

        # Read kind first without a row lock. OPEN terminal transitions then
        # acquire the Firm guard before locking the intent, matching Phase-A
        # lock ordering. CLOSE/risk-reducing paths never depend on this guard.
        intent_preview = conn.execute(
            sa.select(intents).where(
                intents.c.order_intent_id == order_intent_id
            )
        ).mappings().first()
        if intent_preview is None:
            raise KeyError(f"unknown order intent: {order_intent_id}")
        if str(intent_preview["intent_kind"]) == "OPEN":
            self._lock_firm_risk_admission_guard(conn)

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

        released_stop_risk_usd: float | None = None
        if is_failed_open:
            risk_row = conn.execute(
                sa.select(risk_reservations)
                .where(
                    risk_reservations.c.order_intent_id
                    == order_intent_id
                )
                .with_for_update()
            ).mappings().first()
            if risk_row is not None:
                released_stop_risk_usd = float(
                    risk_row["stop_risk_usd"]
                )
                conn.execute(
                    risk_reservations.delete().where(
                        risk_reservations.c.order_intent_id
                        == order_intent_id
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
                "released_stop_risk_usd": released_stop_risk_usd,
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
        lineage = self.tables["decision_lineage"]

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

            hitch_usd: tuple[tuple[str, float], ...] = ()
            firm_event_id = trade["firm_event_id"]
            if firm_event_id is not None:
                lineage_row = conn.execute(
                    sa.select(lineage).where(
                        lineage.c.firm_event_id == firm_event_id
                    )
                ).mappings().first()
                if lineage_row is None:
                    raise RuntimeError(
                        f"OpenTrade missing decision lineage: {trade['trade_id']}"
                    )
                hitches = {
                    str(target): float(fraction)
                    for target, fraction in dict(
                        lineage_row["asset_risk_hitches"] or {}
                    ).items()
                }
                playbook_id = lineage_row["playbook_id"]
                if playbook_id is not None:
                    expected_hitches = {
                        str(target): float(fraction)
                        for target, fraction in asset_risk_hitches(
                            str(playbook_id)
                        ).items()
                    }
                    if hitches != expected_hitches:
                        raise RuntimeError(
                            f"OpenTrade playbook Risk hitch drift: {trade['trade_id']}"
                        )
                hitch_usd = tuple(
                    (target_asset, computed_risk * fraction)
                    for target_asset, fraction in sorted(hitches.items())
                )

            rows.append(
                BookRiskPosition(
                    trade_id=str(trade["trade_id"]),
                    position_key=position_key,
                    asset_id=asset_id,
                    cluster_id=cluster_id,
                    stop_risk_usd=computed_risk,
                    asset_risk_hitches_usd=hitch_usd,
                )
            )

        return aggregate_book_risk(rows)

    def event_rows(self, conn: Connection) -> list[dict[str, Any]]:
        table = self.tables["event_ledger"]
        rows = conn.execute(
            sa.select(table).order_by(table.c.created_at_utc, table.c.event_id)
        ).mappings()
        return [dict(row) for row in rows]
