"""Canonical AETHER reason-code vocabulary.

Free-text reasons may add detail, but first_kill_reason must use a canonical code.
"""
from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    # Universe Radar / market infrastructure
    UNSUPPORTED_PRODUCT = "unsupported_product"
    NO_MARKET_ADAPTER = "no_market_adapter"
    QUOTE_STALE = "quote_stale"
    LIFECYCLE_INELIGIBLE = "lifecycle_ineligible"
    BROKER_HALT = "broker_halt"

    # Scout
    NO_SETUP = "no_setup"
    GRAIN_CONFLICT = "grain_conflict"
    SESSION_CLOSED = "session_closed"
    ROUTE_BENCHED = "route_benched"
    EVENT_RISK = "event_risk"

    # Sniper
    FORMING_BAR = "forming_bar"
    INVALIDATION_HIT = "invalidation_hit"
    NO_COMPLETED_BREAKOUT = "no_completed_breakout"
    STALE_SETUP = "stale_setup"
    SIGNAL_KEY_DUPLICATE = "signal_key_duplicate"

    # Risk
    BAD_STOP = "bad_stop"
    TOO_SMALL = "too_small"
    ASSET_RISK_FULL = "asset_risk_full"
    CLUSTER_RISK_FULL = "cluster_risk_full"
    PORTFOLIO_RISK_FULL = "portfolio_risk_full"
    INSUFFICIENT_CAPITAL = "insufficient_capital"
    BOOK_HORIZON_OPEN = "book_horizon_open"
    SIDE_NOT_SUPPORTED = "side_not_supported"
    PRODUCT_SIDE_UNSUPPORTED = "product_side_unsupported"
    PRODUCT_CAP = "product_cap"

    # Clerk
    COST_HURDLE_EXCEEDS_EXPECTED_MOVE = "cost_hurdle_exceeds_expected_move"
    PRODUCT_COST_MODEL_ERROR = "product_cost_model_error"

    # Portfolio Phase-A contract
    TICKET_NOT_READY = "ticket_not_ready"
    CONFIGURATION_MISMATCH = "configuration_mismatch"
    TICKET_CONTRACT_MISMATCH = "ticket_contract_mismatch"

    # Portfolio / execution
    SIGNAL_CONSUMED = "signal_consumed"
    BROKER_REJECT = "broker_reject"
    MARGIN_CHANGED = "margin_changed"
    MARKET_CHANGED = "market_changed"
    MARKET_STALE = "market_stale"
    BAD_FILL_THROUGH_STOP = "bad_fill_through_stop"
    DUPLICATE_POSITION_KEY = "duplicate_position_key"

    # Governor
    ROUTE_HALTED = "route_halted"
    VENUE_HALTED = "venue_halted"
    DESK_HALTED = "desk_halted"

    # Exit
    PLAN_COMPLETE = "plan_complete"
