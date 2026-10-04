from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.market_fabric_consumers import (
    ConsumerGatePolicy,
    clerk_execution_context,
    project_executable_market_observation,
    risk_market_context,
    strategy_market_context,
)
from aether_vnext.market_fabric_tape import (
    EvidenceState,
    ExecutableTapeSnapshot,
    ExecutionState,
    MarketIntelligenceSnapshot,
)


UTC = timezone.utc
POLICY = ConsumerGatePolicy(
    policy_version="consumer-fixture-v1",
    allowed_evidence_states=frozenset({EvidenceState.FULL, EvidenceState.DEGRADED}),
)


def _exec(state: ExecutionState = ExecutionState.EXECUTABLE):
    return ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-paper",
        authorized_economic_source_id="kraken_spot",
        state=state,
        bid=100000.0 if state is ExecutionState.EXECUTABLE else None,
        ask=100002.0 if state is ExecutionState.EXECUTABLE else None,
        last_if_printed=100001.0,
        last_credible_age_ms=20,
    )


def _intel(state: EvidenceState = EvidenceState.FULL):
    return MarketIntelligenceSnapshot(
        instrument_id="btc_usd",
        evidence_state=state,
        quorum_met=state is EvidenceState.FULL,
        raw_witness_count=3,
        effective_independent_count=3,
        in_band_count=3 if state is EvidenceState.FULL else 0,
        outside_count=0,
        pending_count=0,
        max_gap_bps=1.0,
        mutual_spread_bps=2.0,
        classifications=(),
    )


def test_strategy_and_risk_use_two_state_axes() -> None:
    strategy = strategy_market_context(_exec(), _intel(), policy=POLICY)
    risk = risk_market_context(_exec(), _intel(), policy=POLICY)

    assert strategy.entry_market_ready is True
    assert risk.entry_market_ready is True
    assert risk.execution_state is ExecutionState.EXECUTABLE
    assert risk.evidence_state is EvidenceState.FULL


def test_contested_intelligence_closes_entry_without_repricing_executable_book() -> None:
    executable = _exec()
    strategy = strategy_market_context(
        executable,
        _intel(EvidenceState.CONTESTED),
        policy=POLICY,
    )

    assert strategy.entry_market_ready is False
    assert executable.bid == 100000.0
    assert executable.ask == 100002.0


def test_clerk_receives_only_authorized_executable_route_book() -> None:
    clerk = clerk_execution_context(_exec())

    assert clerk.route_id == "btc-paper"
    assert clerk.authorized_economic_source_id == "kraken_spot"
    assert clerk.bid == 100000.0
    assert clerk.ask == 100002.0
    assert clerk.intelligence_reference_only is True


def test_clerk_refuses_stale_or_not_observed_market_truth() -> None:
    with pytest.raises(RuntimeError, match="EXECUTABLE"):
        clerk_execution_context(_exec(ExecutionState.STALE))


def test_existing_market_ledger_projection_uses_executable_price_not_consensus() -> None:
    observation = project_executable_market_observation(
        _exec(),
        asset_id="btc",
        session_state="OPEN",
        calendar_state="OPEN",
        observed_at_utc=datetime(2026, 10, 4, 5, 0, tzinfo=UTC),
        data_version="market-fabric-v3",
    )

    assert observation is not None
    assert observation.venue == "kraken_spot"
    assert observation.bid == 100000.0
    assert observation.ask == 100002.0
    assert observation.mark == 100001.0
    assert observation.source == "aether_market_fabric_executable_tape"
