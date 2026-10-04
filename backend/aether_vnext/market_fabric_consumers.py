"""MF-11 dual-domain Market Fabric consumer contracts.

Strategy and Risk consume executable truth plus Market Intelligence as separate axes.
Clerk receives only authorized executable-route pricing/depth context. No consumer may
replace an executable price with witness-derived or composite pricing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import FrozenSet

from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.market_fabric_tape import (
    EvidenceState,
    ExecutableTapeSnapshot,
    ExecutionState,
    MarketIntelligenceSnapshot,
)


@dataclass(frozen=True, slots=True)
class ConsumerGatePolicy:
    policy_version: str
    allowed_evidence_states: FrozenSet[EvidenceState]

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if not self.allowed_evidence_states:
            raise ValueError("allowed_evidence_states cannot be empty")


@dataclass(frozen=True, slots=True)
class StrategyMarketContext:
    executable: ExecutableTapeSnapshot
    intelligence: MarketIntelligenceSnapshot
    entry_market_ready: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RiskMarketContext:
    execution_state: ExecutionState
    evidence_state: EvidenceState
    quorum_met: bool
    executable_price_observed: bool
    entry_market_ready: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ClerkExecutionContext:
    instrument_id: str
    route_id: str
    authorized_economic_source_id: str
    bid: float
    ask: float
    last_if_printed: float | None
    intelligence_reference_only: bool = True


def strategy_market_context(
    executable: ExecutableTapeSnapshot,
    intelligence: MarketIntelligenceSnapshot,
    *,
    policy: ConsumerGatePolicy,
) -> StrategyMarketContext:
    if intelligence.instrument_id != executable.instrument_id:
        raise ValueError("dual-domain instrument mismatch")
    if executable.state is not ExecutionState.EXECUTABLE:
        return StrategyMarketContext(
            executable=executable,
            intelligence=intelligence,
            entry_market_ready=False,
            reason=f"executable_state:{executable.state.value}",
        )
    if intelligence.evidence_state not in policy.allowed_evidence_states:
        return StrategyMarketContext(
            executable=executable,
            intelligence=intelligence,
            entry_market_ready=False,
            reason=f"evidence_state:{intelligence.evidence_state.value}",
        )
    return StrategyMarketContext(
        executable=executable,
        intelligence=intelligence,
        entry_market_ready=True,
        reason="market_fabric_ready",
    )


def risk_market_context(
    executable: ExecutableTapeSnapshot,
    intelligence: MarketIntelligenceSnapshot,
    *,
    policy: ConsumerGatePolicy,
) -> RiskMarketContext:
    strategy = strategy_market_context(
        executable,
        intelligence,
        policy=policy,
    )
    return RiskMarketContext(
        execution_state=executable.state,
        evidence_state=intelligence.evidence_state,
        quorum_met=intelligence.quorum_met,
        executable_price_observed=(
            executable.state is ExecutionState.EXECUTABLE
            and executable.bid is not None
            and executable.ask is not None
        ),
        entry_market_ready=strategy.entry_market_ready,
        reason=strategy.reason,
    )


def clerk_execution_context(
    executable: ExecutableTapeSnapshot,
) -> ClerkExecutionContext:
    if executable.state is not ExecutionState.EXECUTABLE:
        raise RuntimeError("Clerk requires EXECUTABLE authorized-route market truth")
    if executable.bid is None or executable.ask is None:
        raise RuntimeError("Clerk executable bid/ask unavailable")
    return ClerkExecutionContext(
        instrument_id=executable.instrument_id,
        route_id=executable.route_id,
        authorized_economic_source_id=executable.authorized_economic_source_id,
        bid=float(executable.bid),
        ask=float(executable.ask),
        last_if_printed=executable.last_if_printed,
    )


def project_executable_market_observation(
    executable: ExecutableTapeSnapshot,
    *,
    asset_id: str,
    session_state: str,
    calendar_state: str,
    observed_at_utc: datetime,
    data_version: str,
) -> MarketObservation | None:
    """Project only authorized executable truth into the existing market ledger.

    Witness/evidence data is deliberately absent from price construction. Consumers
    that need evidence receive it through StrategyMarketContext/RiskMarketContext.
    """
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    if executable.state is not ExecutionState.EXECUTABLE:
        return None
    if executable.bid is None or executable.ask is None:
        return None
    bid = float(executable.bid)
    ask = float(executable.ask)
    mid = (bid + ask) / 2.0
    identity = "|".join(
        (
            executable.instrument_id,
            executable.route_id,
            executable.authorized_economic_source_id,
            observed_at_utc.astimezone(timezone.utc).isoformat(),
            str(bid),
            str(ask),
        )
    )
    return MarketObservation(
        observation_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        asset_id=str(asset_id).strip().lower(),
        venue=executable.authorized_economic_source_id,
        bid=bid,
        ask=ask,
        last=executable.last_if_printed,
        mark=mid,
        source="aether_market_fabric_executable_tape",
        exchange_ts=None,
        received_ts=observed_at_utc,
        age_ms=int(executable.last_credible_age_ms or 0),
        spread_abs=ask - bid,
        spread_bps=(ask - bid) / mid * 10_000.0,
        session_state=session_state,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=calendar_state,
        data_version=str(data_version),
    )
