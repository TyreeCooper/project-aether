"""AETHER vNext paper execution foundation.

Implements only frozen, unambiguous execution law:
- two-phase lifecycle shape;
- immediate SUBMITTED acknowledgement;
- 250 ms paper fill latency;
- 15 s paper stale-submit timeout;
- all-or-none seed-twelve fills by default;
- long entry from ask + adverse slip; short entry from bid - adverse slip;
- protective stop tests on bid for longs / ask for shorts;
- gap-through stop exits at conservative through-price + adverse slip;
- stale/invalid/session-ineligible/spread-doubled fill-time rejection;
- terminal state wins.

The source phrase for entry bad_fill_through_stop is intentionally NOT encoded
here because the binding documents state a long entry is invalid when
fill >= stop while the same playbooks define protective long stops below entry.
That ambiguity is tracked in AETH-VN-004 and must be resolved rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from aether_vnext.costs import DEFAULT_SLIP_BPS, slip_cost_usd
from aether_vnext.domain import (
    MarketObservation,
    OrderIntent,
    OrderIntentState,
    QualityState,
    SessionState,
    Ticket,
    TicketState,
)
from aether_vnext.market_truth import observation_is_valid
from aether_vnext.registry import ProductRegistryRow


PAPER_ACK_MS = 250
PAPER_SUBMIT_TIMEOUT_MS = 15_000

_TERMINAL_STATES = frozenset(
    {
        OrderIntentState.FILLED,
        OrderIntentState.REJECTED,
        OrderIntentState.CANCELLED,
        OrderIntentState.CANCELLED_STALE,
    }
)


@dataclass(frozen=True, slots=True)
class PaperExecutionPolicy:
    paper_ack_ms: int = PAPER_ACK_MS
    submit_timeout_ms: int = PAPER_SUBMIT_TIMEOUT_MS
    slip_bps: float = DEFAULT_SLIP_BPS
    partials_enabled: bool = False

    def __post_init__(self) -> None:
        if self.paper_ack_ms < 0:
            raise ValueError("paper_ack_ms cannot be negative")
        if self.submit_timeout_ms <= 0:
            raise ValueError("submit_timeout_ms must be positive")
        if self.slip_bps < 0:
            raise ValueError("slip_bps cannot be negative")


@dataclass(frozen=True, slots=True)
class PhaseAAdmissionDecision:
    allowed: bool
    reason: str


def phase_a_admission(
    *,
    ticket: Ticket,
    observation: MarketObservation,
    registry_row: ProductRegistryRow,
    active_configuration_hash: str,
    max_age_ms: int,
    route_evidence_state: str,
    route_operational_state: str,
    governor_halted: bool,
    firm_envelope_ok: bool,
    firm_envelope_reason: str = "portfolio_risk_full",
    locate_ok: bool = False,
) -> PhaseAAdmissionDecision:
    """Pure pre-reserve gate; broker capacity and DB uniqueness are store-owned."""
    if ticket.state is not TicketState.READY:
        return PhaseAAdmissionDecision(False, "ticket_not_ready")
    if ticket.lineage.configuration_hash != active_configuration_hash:
        return PhaseAAdmissionDecision(False, "configuration_mismatch")
    if ticket.quantity is None or float(ticket.quantity) <= 0:
        return PhaseAAdmissionDecision(False, "too_small")
    if ticket.lineage.asset_id != registry_row.asset_id:
        return PhaseAAdmissionDecision(False, "unsupported_product")
    if observation.asset_id != registry_row.asset_id:
        return PhaseAAdmissionDecision(False, "market_changed")
    if route_evidence_state == "BENCH":
        return PhaseAAdmissionDecision(False, "route_benched")
    if route_operational_state != "ENABLED" or governor_halted:
        return PhaseAAdmissionDecision(False, "route_halted")
    if not registry_row.product_side_supported(
        ticket.side,
        locate_ok=locate_ok,
    ):
        return PhaseAAdmissionDecision(False, "product_side_unsupported")
    if not firm_envelope_ok:
        return PhaseAAdmissionDecision(False, firm_envelope_reason)
    if not observation_is_valid(
        observation,
        max_age_ms=max_age_ms,
    ):
        if observation.session_state in {
            SessionState.CLOSED,
            SessionState.MAINTENANCE,
            SessionState.HALT,
        }:
            return PhaseAAdmissionDecision(False, "session_closed")
        return PhaseAAdmissionDecision(False, "market_stale")
    return PhaseAAdmissionDecision(True, "phase_a_ready")


@dataclass(frozen=True, slots=True)
class ExecutionTransition:
    intent: OrderIntent
    applied: bool
    reason: str


def submit_paper_intent(
    intent: OrderIntent,
    *,
    at_utc: datetime,
) -> ExecutionTransition:
    _require_aware(at_utc, "at_utc")
    if intent.state in _TERMINAL_STATES:
        return ExecutionTransition(intent, False, "terminal_state_wins")
    if intent.state is not OrderIntentState.RESERVED:
        return ExecutionTransition(intent, False, "illegal_state")
    updated = replace(
        intent,
        state=OrderIntentState.SUBMITTED,
        submitted_at=at_utc,
        acknowledged_at=at_utc,
    )
    return ExecutionTransition(updated, True, "submitted")


def paper_fill_due_at(
    intent: OrderIntent,
    *,
    policy: PaperExecutionPolicy = PaperExecutionPolicy(),
) -> datetime:
    base = intent.acknowledged_at or intent.submitted_at
    if base is None:
        raise ValueError("submitted/acknowledged timestamp required")
    _require_aware(base, "submitted_at")
    return base + timedelta(milliseconds=policy.paper_ack_ms)


def paper_submit_timeout_at(
    intent: OrderIntent,
    *,
    policy: PaperExecutionPolicy = PaperExecutionPolicy(),
) -> datetime:
    base = intent.submitted_at
    if base is None:
        raise ValueError("submitted_at required")
    _require_aware(base, "submitted_at")
    return base + timedelta(milliseconds=policy.submit_timeout_ms)


def cancel_stale_paper_intent(
    intent: OrderIntent,
    *,
    at_utc: datetime,
    policy: PaperExecutionPolicy = PaperExecutionPolicy(),
) -> ExecutionTransition:
    _require_aware(at_utc, "at_utc")
    if intent.state in _TERMINAL_STATES:
        return ExecutionTransition(intent, False, "terminal_state_wins")
    if intent.state not in {
        OrderIntentState.RESERVED,
        OrderIntentState.SUBMITTED,
    }:
        return ExecutionTransition(intent, False, "illegal_state")

    if intent.submitted_at is None:
        base = intent.lineage.created_at_utc
        _require_aware(base, "lineage.created_at_utc")
        timeout_at = base + timedelta(milliseconds=policy.submit_timeout_ms)
    else:
        timeout_at = paper_submit_timeout_at(intent, policy=policy)

    if at_utc <= timeout_at:
        return ExecutionTransition(intent, False, "not_stale")

    updated = replace(
        intent,
        state=OrderIntentState.CANCELLED_STALE,
        reject_code="submit_timeout",
    )
    return ExecutionTransition(updated, True, "cancelled_stale")


def entry_fill_price(
    observation: MarketObservation,
    *,
    position_side: str,
    slip_bps: float = DEFAULT_SLIP_BPS,
) -> float:
    side = _position_side(position_side)
    if slip_bps < 0:
        raise ValueError("slip_bps cannot be negative")
    if side == "long":
        if observation.ask is None or observation.ask <= 0:
            raise ValueError("valid ask required for long entry")
        return float(observation.ask) * (1.0 + slip_bps / 10_000.0)
    if observation.bid is None or observation.bid <= 0:
        raise ValueError("valid bid required for short entry")
    return float(observation.bid) * (1.0 - slip_bps / 10_000.0)


def exit_fill_price(
    observation: MarketObservation,
    *,
    position_side: str,
    slip_bps: float = DEFAULT_SLIP_BPS,
) -> float:
    """Conservative non-stop flatten price: long sells bid, short buys ask."""
    side = _position_side(position_side)
    if slip_bps < 0:
        raise ValueError("slip_bps cannot be negative")
    if side == "long":
        if observation.bid is None or observation.bid <= 0:
            raise ValueError("valid bid required for long exit")
        return float(observation.bid) * (1.0 - slip_bps / 10_000.0)
    if observation.ask is None or observation.ask <= 0:
        raise ValueError("valid ask required for short exit")
    return float(observation.ask) * (1.0 + slip_bps / 10_000.0)


def stop_triggered(
    observation: MarketObservation,
    *,
    position_side: str,
    hard_stop_price: float,
) -> bool:
    side = _position_side(position_side)
    stop = float(hard_stop_price)
    if stop <= 0:
        raise ValueError("hard_stop_price must be positive")
    if side == "long":
        return observation.bid is not None and float(observation.bid) <= stop
    return observation.ask is not None and float(observation.ask) >= stop


def stop_exit_fill_price(
    observation: MarketObservation,
    *,
    position_side: str,
    hard_stop_price: float,
    slip_bps: float = DEFAULT_SLIP_BPS,
) -> float:
    """Fill a protective stop at the through-price, never a perfect stop."""
    side = _position_side(position_side)
    stop = float(hard_stop_price)
    if stop <= 0:
        raise ValueError("hard_stop_price must be positive")
    if slip_bps < 0:
        raise ValueError("slip_bps cannot be negative")

    if side == "long":
        if observation.bid is None or observation.bid <= 0:
            raise ValueError("valid bid required for long stop exit")
        reference = min(stop, float(observation.bid))
        return reference * (1.0 - slip_bps / 10_000.0)

    if observation.ask is None or observation.ask <= 0:
        raise ValueError("valid ask required for short stop exit")
    reference = max(stop, float(observation.ask))
    return reference * (1.0 + slip_bps / 10_000.0)


def fill_submitted_paper_intent(
    intent: OrderIntent,
    *,
    observation: MarketObservation,
    registry_row: ProductRegistryRow,
    ready_spread_bps: float,
    hard_stop_price: float,
    max_age_ms: int,
    at_utc: datetime,
    policy: PaperExecutionPolicy = PaperExecutionPolicy(),
) -> ExecutionTransition:
    """Apply the seed-twelve all-or-none paper Phase-B decision."""
    _require_aware(at_utc, "at_utc")
    if intent.state in _TERMINAL_STATES:
        return ExecutionTransition(intent, False, "terminal_state_wins")
    if intent.state is not OrderIntentState.SUBMITTED:
        return ExecutionTransition(intent, False, "illegal_state")
    if at_utc < paper_fill_due_at(intent, policy=policy):
        return ExecutionTransition(intent, False, "paper_latency_wait")
    if policy.partials_enabled:
        return ExecutionTransition(intent, False, "partial_policy_not_implemented")

    reject = fill_time_reject_code(
        observation,
        position_side=intent.side,
        hard_stop_price=hard_stop_price,
        ready_spread_bps=ready_spread_bps,
        max_age_ms=max_age_ms,
    )
    if reject is not None:
        updated = replace(
            intent,
            state=OrderIntentState.REJECTED,
            reject_code=reject,
        )
        return ExecutionTransition(updated, True, reject)

    fill_price = entry_fill_price(
        observation,
        position_side=intent.side,
        slip_bps=policy.slip_bps,
    )
    reference_price = (
        observation.ask
        if intent.side.lower() == "long"
        else observation.bid
    )
    if reference_price is None:
        raise ValueError("entry quote side missing")
    slip_usd = slip_cost_usd(
        registry_row,
        qty=intent.qty,
        price=reference_price,
        slip_bps=policy.slip_bps,
    )
    updated = replace(
        intent,
        state=OrderIntentState.FILLED,
        filled_at=at_utc,
        filled_qty=intent.qty,
        avg_fill_price=fill_price,
        reject_code=None,
        slippage_usd=slip_usd,
        slippage_bps=policy.slip_bps,
    )
    return ExecutionTransition(updated, True, "filled")


def fill_time_reject_code(
    observation: MarketObservation,
    *,
    position_side: str,
    hard_stop_price: float,
    ready_spread_bps: float,
    max_age_ms: int,
) -> str | None:
    if ready_spread_bps < 0:
        raise ValueError("ready_spread_bps cannot be negative")
    if observation.quality_state in {QualityState.STALE, QualityState.INVALID}:
        return "market_stale"
    if observation.age_ms > max_age_ms:
        return "market_stale"
    if observation.session_state in {
        SessionState.CLOSED,
        SessionState.MAINTENANCE,
        SessionState.HALT,
    }:
        return "market_changed"
    if not observation_is_valid(observation, max_age_ms=max_age_ms):
        return "market_stale"
    if stop_triggered(
        observation,
        position_side=position_side,
        hard_stop_price=hard_stop_price,
    ):
        return "market_changed"
    if observation.spread_bps is None:
        return "market_changed"
    if float(observation.spread_bps) > 2.0 * float(ready_spread_bps):
        return "market_changed"
    return None


def _position_side(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in {"long", "short"}:
        raise ValueError("position_side must be long or short")
    return normalized


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
