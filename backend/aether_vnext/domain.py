"""Canonical AETHER vNext domain objects.

These types encode the Master Blueprint book-of-record identities and lineage.
They are intentionally strategy-agnostic and import no legacy runtime modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SessionState(StrEnum):
    ACTIVE = "active"
    FOCUS = "focus"
    CLOSED = "closed"
    MAINTENANCE = "maintenance"
    HALT = "halt"


class QualityState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    INVALID = "invalid"


class CalendarState(StrEnum):
    HOLIDAY = "holiday"
    EARLY_CLOSE = "early_close"
    NORMAL = "normal"
    ALWAYS_OPEN = "24x7"


class SetupState(StrEnum):
    NO = "NO"
    WATCH = "WATCH"
    FIRE = "FIRE"


class TicketState(StrEnum):
    FIRE = "FIRE"
    SIZE = "SIZE"
    READY = "READY"
    REJECTED = "REJECTED"


class OrderIntentState(StrEnum):
    RESERVED = "RESERVED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CANCELLED_STALE = "CANCELLED_STALE"


@dataclass(frozen=True, slots=True)
class Lineage:
    asset_id: str
    route_id: str
    policy_version: str
    configuration_hash: str
    market_observation_id: str
    created_at_utc: datetime
    firm_event_id: str | None = None
    setup_id: str | None = None
    ticket_id: str | None = None
    order_intent_id: str | None = None
    trade_id: str | None = None
    first_killed_by: str | None = None
    first_kill_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MarketObservation:
    observation_id: str
    asset_id: str
    venue: str
    bid: float | None
    ask: float | None
    last: float | None
    mark: float | None
    source: str
    exchange_ts: datetime | None
    received_ts: datetime
    age_ms: int
    spread_abs: float | None
    spread_bps: float | None
    session_state: SessionState
    quality_state: QualityState
    fallback_reason: str | None
    calendar_state: CalendarState
    data_version: str


@dataclass(frozen=True, slots=True)
class Setup:
    setup_id: str
    lineage: Lineage
    state: SetupState
    side: str
    horizon: str
    invalidation: float | None
    quality: float | None
    intel_pack: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_id: str
    lineage: Lineage
    state: TicketState
    signal_key: str
    side: str
    horizon: str
    stop_price: float | None
    quantity: float | None
    modeled_round_trip_cost_pct: float | None
    reject_code: str | None = None
    exit_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderIntent:
    order_intent_id: str
    lineage: Lineage
    broker: str
    venue: str
    symbol: str
    side: str
    qty: float
    order_type: str
    reference_price: float | None
    expected_fill: float | None
    state: OrderIntentState
    submitted_at: datetime | None
    acknowledged_at: datetime | None
    filled_at: datetime | None
    filled_qty: float
    avg_fill_price: float | None
    reject_code: str | None
    slippage_usd: float | None
    slippage_bps: float | None
    idempotency_key: str
    broker_account_id: str | None = None
    intent_kind: str = "OPEN"
    exit_reason: str | None = None
    position_key: str | None = None
    signal_key: str | None = None
    reserved_cash_usd: float = 0.0
    reserved_margin_usd: float = 0.0
    ready_spread_bps: float | None = None
    hard_stop_price: float | None = None
    submit_timeout_at: datetime | None = None
    fill_market_observation_id: str | None = None
    trade_id: str | None = None
    row_version: int = 1


@dataclass(frozen=True, slots=True)
class OpenTrade:
    trade_id: str
    lineage: Lineage
    position_key: str
    side: str
    quantity: float
    avg_entry_price: float
    initial_stop_risk_usd: float
    exit_plan_version: str
    exit_plan_payload: dict[str, Any]
    opened_at_utc: datetime
    management_telemetry: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    trade_id: str
    lineage: Lineage
    route_id: str
    asset_id: str
    position_key: str
    side: str
    quantity: float
    avg_entry_price: float
    exit_price: float
    closed_at_utc: datetime
    gross_pnl_usd: float
    net_pnl_usd: float
    total_cost_usd: float
    fees_usd: float
    mfe_usd: float | None
    mae_usd: float | None
    capture_efficiency: float | None
    duration_s: float
    exit_reason: str


@dataclass(frozen=True, slots=True)
class ReviewCard:
    review_card_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    as_of_utc: datetime
    evidence_state: str
    evidence_id: str | None
    decision_reason: str
    reviewer: str
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class GovernorStateRecord:
    governor_state_version: str
    state: str
    policy_version: str
    configuration_hash: str
    effective_at_utc: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    policy_version: str
    configuration_hash: str
    effective_at_utc: datetime
    changed_by: str
    change_reason: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BrokerAccountLedger:
    broker_account_id: str
    cash_available_usd: float
    cash_reserved_usd: float
    margin_used_usd: float
    margin_available_usd: float
    realized_pnl_usd: float
    unrealized_pnl_usd: float
    fees_accrued_usd: float
    settled_cash_usd: float | None
    last_reconciled_at: datetime | None
    reconciliation_state: str


@dataclass(frozen=True, slots=True)
class EventLedgerRecord:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    prior_state: str | None
    new_state: str
    seat: str
    reason_code: str
    policy_version: str
    configuration_hash: str
    market_observation_id: str | None
    actor: str
    created_at_utc: datetime
    payload_hash: str
