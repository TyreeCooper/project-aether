"""Crash-resumable BTC/ETH PAPER entry state machine for the vNext prototype.

The state machine composes existing seat bridges only. It does not bypass Scout,
Sniper, Risk, Clerk, Portfolio, Governor, Product Registry, or paper execution.
A newly submitted paper order is not filled in the same pass; a later supervisor
cycle must observe the 250ms paper-latency contract and re-enter here.

LIVE remains hard blocked by every execution bridge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import (
    MarketObservation,
    OrderIntentState,
    SetupState,
    TicketState,
)
from aether_vnext.freeze import CONFIGURATION_HASH, LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.prototype_crypto_entry_plan import (
    PROTOTYPE_COST_EDGE_MULTIPLE,
    PrototypeCryptoEntryPlan,
)
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.runtime_clerk_bridge import evaluate_and_persist_clerk_ready
from aether_vnext.runtime_cycle import ClosedBarCycleResult
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from aether_vnext.runtime_portfolio_bridge import reserve_runtime_ready_ticket
from aether_vnext.runtime_risk_bridge import size_runtime_fire_ticket
from aether_vnext.runtime_scout_bridge import (
    WatchMaterialization,
    persist_cycle_watch_setups,
)
from aether_vnext.runtime_sniper_bridge import evaluate_and_persist_sniper_ticket
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class PrototypeEntryAdvanceResult:
    asset_id: str
    trigger_close_utc: datetime
    stage: str
    reason: str
    setup_id: str
    ticket_id: str
    order_intent_id: str
    trade_id: str | None


def _result(
    plan: PrototypeCryptoEntryPlan,
    *,
    stage: str,
    reason: str,
    order_intent_id: str | None = None,
    trade_id: str | None = None,
) -> PrototypeEntryAdvanceResult:
    return PrototypeEntryAdvanceResult(
        asset_id=plan.asset_id,
        trigger_close_utc=plan.trigger_close_utc,
        stage=stage,
        reason=reason,
        setup_id=plan.ids.setup_id,
        ticket_id=plan.ids.ticket_id,
        order_intent_id=order_intent_id or plan.ids.order_intent_id,
        trade_id=trade_id,
    )


def _policy_version(
    conn: Connection,
    store: VNextStore,
) -> str:
    policies = store.tables["policy_snapshots"]
    row = conn.execute(
        sa.select(policies.c.policy_version).where(
            policies.c.configuration_hash == CONFIGURATION_HASH
        )
    ).first()
    if row is None:
        raise RuntimeError(
            "prototype entry requires the active frozen policy snapshot"
        )
    value = str(row[0]).strip()
    if not value:
        raise RuntimeError("prototype policy_version is blank")
    return value


def _require_completed_kraken_hour(
    bar: PrototypeMarketBar,
    plan: PrototypeCryptoEntryPlan,
    *,
    as_of_utc: datetime,
) -> None:
    if bar.asset_id != plan.asset_id:
        raise ValueError("completed trigger bar asset mismatch")
    if bar.interval_seconds != 3600:
        raise ValueError("prototype entry requires a completed 1h trigger bar")
    if bar.bucket_close_utc != plan.trigger_close_utc:
        raise ValueError("completed trigger bar does not match entry plan")
    if bar.bucket_close_utc > as_of_utc:
        raise ValueError("future trigger bar cannot enter runtime")
    if bar.available_at_utc > as_of_utc:
        raise ValueError("unavailable trigger bar cannot enter runtime")
    if bar.source_id != KRAKEN_DAILY_SOURCE_ID:
        raise ValueError(
            "prototype decision-critical trigger bar must be direct Kraken REST"
        )


def advance_prototype_crypto_entry(
    conn: Connection,
    store: VNextStore,
    *,
    plan: PrototypeCryptoEntryPlan,
    completed_bar: PrototypeMarketBar,
    current_observation: MarketObservation,
    current_observations: Mapping[str, MarketObservation],
    as_of_utc: datetime,
) -> PrototypeEntryAdvanceResult:
    """Advance one deterministic closed-bar candidate as far as safely possible."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype entry requires PAPER_ONLY/LIVE_BLOCKED")
    if current_observation.asset_id != plan.asset_id:
        raise ValueError("current observation asset mismatch")
    mapped = current_observations.get(plan.asset_id)
    if mapped is None or mapped.observation_id != current_observation.observation_id:
        raise ValueError("current_observations must contain current asset observation")
    _require_completed_kraken_hour(
        completed_bar,
        plan,
        as_of_utc=as_of_utc,
    )

    if not plan.eligible:
        return _result(plan, stage="NO_SETUP", reason=plan.reason)
    if plan.geometry is None or plan.exit_plan is None:
        raise RuntimeError("eligible prototype entry missing exit geometry")
    if plan.estimated_cost_per_unit is None:
        raise RuntimeError("eligible prototype entry missing cost estimate")
    candidates = plan.runtime_decision.watch_candidates
    if len(candidates) != 1:
        raise RuntimeError("prototype entry requires exactly one WATCH candidate")
    candidate = candidates[0]

    policy_version = _policy_version(conn, store)

    setup = store.load_setup(conn, setup_id=plan.ids.setup_id)
    if setup is None:
        cycle = ClosedBarCycleResult(
            asset_id=plan.asset_id,
            horizon="daily_swing",
            trigger_bar_open_utc=completed_bar.bucket_open_utc,
            trigger_bar_close_utc=completed_bar.bucket_close_utc,
            decision=plan.runtime_decision,
        )
        persist_cycle_watch_setups(
            conn,
            store,
            cycle=cycle,
            materializations=(
                WatchMaterialization(
                    playbook_id=candidate.playbook_id,
                    side=candidate.side,
                    setup_id=plan.ids.setup_id,
                    firm_event_id=plan.ids.firm_event_id,
                    invalidation=plan.geometry.structure_invalidation_level,
                    quality=None,
                    intel_pack={
                        "prototype": True,
                        "phase18_evidence": False,
                        "trigger_source_id": completed_bar.source_id,
                        "atr14": plan.geometry.atr_multiplier
                        if hasattr(plan.geometry, "atr_multiplier")
                        else None,
                        "prior_20h_high": plan.geometry.structure_invalidation_level,
                        "cost_edge_multiple": PROTOTYPE_COST_EDGE_MULTIPLE,
                    },
                ),
            ),
            policy_version=policy_version,
            configuration_hash=CONFIGURATION_HASH,
            market_observation_id=current_observation.observation_id,
            created_at_utc=as_of_utc,
            regime_tags=plan.regime_tags,
        )
        setup = store.load_setup(conn, setup_id=plan.ids.setup_id)
        if setup is None:
            raise RuntimeError("Scout failed to persist prototype WATCH")

    ticket = store.load_ticket(conn, ticket_id=plan.ids.ticket_id)
    if ticket is None:
        if setup.state is not SetupState.WATCH:
            raise RuntimeError("prototype setup advanced without durable ticket")
        _, sniper_result = evaluate_and_persist_sniper_ticket(
            conn,
            store,
            setup_id=plan.ids.setup_id,
            ticket_id=plan.ids.ticket_id,
            completed_bar=completed_bar,
            current_observation=current_observation,
            hard_stop_price=plan.hard_stop_price,
            as_of_utc=as_of_utc,
            grain_valid=True,
            invalidation_hit=plan.invalidation_hit,
            created_at_utc=as_of_utc,
        )
        ticket = store.load_ticket(conn, ticket_id=plan.ids.ticket_id)
        if ticket is None:
            raise RuntimeError("Sniper failed to persist prototype ticket")
        if sniper_result["state"] == TicketState.REJECTED.value:
            return _result(
                plan,
                stage="REJECTED",
                reason=str(sniper_result.get("reject_code") or "sniper_rejected"),
            )

    if ticket.state is TicketState.REJECTED:
        return _result(
            plan,
            stage="REJECTED",
            reason=str(ticket.reject_code or "ticket_rejected"),
        )

    if ticket.state is TicketState.FIRE:
        risk = size_runtime_fire_ticket(
            conn,
            store,
            ticket_id=ticket.ticket_id,
            current_observation=current_observation,
            current_observations=current_observations,
            estimated_round_trip_cost_per_unit_usd=float(
                plan.estimated_cost_per_unit.total_round_trip_cost_usd
            ),
            created_at_utc=as_of_utc,
            event_id=plan.ids.event_id("risk"),
        )
        if risk["state"] == TicketState.REJECTED.value:
            return _result(
                plan,
                stage="REJECTED",
                reason=str(risk.get("reject_code") or "risk_rejected"),
            )
        ticket = store.load_ticket(conn, ticket_id=plan.ids.ticket_id)
        if ticket is None:
            raise RuntimeError("Risk lost prototype ticket")

    if ticket.state is TicketState.SIZE:
        _, clerk = evaluate_and_persist_clerk_ready(
            conn,
            store,
            ticket_id=ticket.ticket_id,
            current_observation=current_observation,
            first_target_price=plan.first_target_price,
            atr=None,
            locate_ok=False,
            exit_plan=plan.exit_plan,
            created_at_utc=as_of_utc,
            event_id=plan.ids.event_id("clerk"),
            cost_edge_multiple=PROTOTYPE_COST_EDGE_MULTIPLE,
        )
        if clerk["state"] == TicketState.REJECTED.value:
            return _result(
                plan,
                stage="REJECTED",
                reason=str(clerk.get("reject_code") or "clerk_rejected"),
            )
        ticket = store.load_ticket(conn, ticket_id=plan.ids.ticket_id)
        if ticket is None:
            raise RuntimeError("Clerk lost prototype ticket")

    if ticket.state is TicketState.REJECTED:
        return _result(
            plan,
            stage="REJECTED",
            reason=str(ticket.reject_code or "ticket_rejected"),
        )
    if ticket.state is not TicketState.READY:
        raise RuntimeError(f"unexpected prototype ticket state: {ticket.state.value}")

    intent = store.load_order_intent(
        conn,
        order_intent_id=plan.ids.order_intent_id,
    )
    order_intent_id = plan.ids.order_intent_id
    if intent is None:
        reserve = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id=ticket.ticket_id,
            order_intent_id=order_intent_id,
            current_observation=current_observation,
            current_observations=current_observations,
            created_at_utc=as_of_utc,
            event_id=plan.ids.event_id("reserve"),
        )
        if not bool(reserve.get("ok")):
            return _result(
                plan,
                stage="REJECTED",
                reason=str(
                    reserve.get("reject_code")
                    or reserve.get("error")
                    or "portfolio_rejected"
                ),
            )
        order_intent_id = str(
            reserve.get("order_intent_id") or order_intent_id
        )
        intent = store.load_order_intent(
            conn,
            order_intent_id=order_intent_id,
        )
        if intent is None:
            raise RuntimeError("Portfolio failed to persist prototype intent")

    if intent.state is OrderIntentState.RESERVED:
        submitted = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id=order_intent_id,
            submitted_at_utc=as_of_utc,
            event_id=plan.ids.event_id("submit"),
        )
        if submitted["state"] != OrderIntentState.SUBMITTED.value:
            return _result(
                plan,
                stage="REJECTED",
                reason=str(submitted.get("error") or "submit_rejected"),
                order_intent_id=order_intent_id,
            )
        # Enforce the paper latency boundary. A later cycle performs the fill.
        return _result(
            plan,
            stage="SUBMITTED",
            reason="paper_latency_wait",
            order_intent_id=order_intent_id,
        )

    if intent.state is OrderIntentState.SUBMITTED:
        filled = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id=order_intent_id,
            trade_id=plan.ids.trade_id,
            fill_market_observation_id=current_observation.observation_id,
            filled_at_utc=as_of_utc,
            event_id=plan.ids.event_id("fill"),
        )
        if filled.get("state") == OrderIntentState.FILLED.value:
            return _result(
                plan,
                stage="OPEN",
                reason="paper_filled",
                order_intent_id=order_intent_id,
                trade_id=str(filled.get("trade_id") or plan.ids.trade_id),
            )
        return _result(
            plan,
            stage="SUBMITTED",
            reason=str(filled.get("reason") or filled.get("error") or "pending"),
            order_intent_id=order_intent_id,
        )

    if intent.state is OrderIntentState.FILLED:
        return _result(
            plan,
            stage="OPEN",
            reason="already_filled",
            order_intent_id=order_intent_id,
            trade_id=str(intent.trade_id or plan.ids.trade_id),
        )

    return _result(
        plan,
        stage="REJECTED",
        reason=str(intent.reject_code or intent.state.value),
        order_intent_id=order_intent_id,
        trade_id=intent.trade_id,
    )
