from __future__ import annotations

from aether_vnext.market_fabric_microstructure import MicrostructureSnapshot
from aether_vnext.market_fabric_operator import (
    build_market_fabric_operator_snapshot,
)
from aether_vnext.market_fabric_tape import (
    EvidenceState,
    ExecutableTapeSnapshot,
    ExecutionState,
    MarketIntelligenceSnapshot,
)


def test_operator_projection_keeps_executable_and_intelligence_separate() -> None:
    executable = ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-paper",
        authorized_economic_source_id="kraken_spot",
        state=ExecutionState.EXECUTABLE,
        bid=100000.0,
        ask=100002.0,
        last_if_printed=100001.0,
        last_credible_age_ms=25,
    )
    intelligence = MarketIntelligenceSnapshot(
        instrument_id="btc_usd",
        evidence_state=EvidenceState.FULL,
        quorum_met=True,
        raw_witness_count=3,
        effective_independent_count=3,
        in_band_count=3,
        outside_count=0,
        pending_count=0,
        max_gap_bps=1.2,
        mutual_spread_bps=1.7,
        classifications=(),
    )
    micro = MicrostructureSnapshot(
        spread_abs=2.0,
        spread_bps=0.2,
        top_depth_bid=5.0,
        top_depth_ask=4.0,
        depth_imbalance=0.111,
        trade_imbalance=0.2,
        quote_velocity_hz=3.0,
        realized_volatility=0.001,
        liquidity_score=7.5,
        market_impact_proxy_bps=4.0,
    )

    payload = build_market_fabric_operator_snapshot(
        rows={"btc_usd": (executable, intelligence, micro)}
    )
    row = payload["instruments"][0]

    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["authority"]["execution_permission"] is False
    assert row["executable"]["bid"] == 100000.0
    assert row["executable"]["ask"] == 100002.0
    assert row["intelligence"]["effective_independent_count"] == 3
    assert row["microstructure"]["executable"] is False


def test_operator_projection_preserves_unknown_as_null() -> None:
    executable = ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-paper",
        authorized_economic_source_id="kraken_spot",
        state=ExecutionState.NOT_OBSERVED,
        bid=None,
        ask=None,
        last_if_printed=None,
        last_credible_age_ms=None,
    )
    intelligence = MarketIntelligenceSnapshot(
        instrument_id="btc_usd",
        evidence_state=EvidenceState.NOT_OBSERVED,
        quorum_met=False,
        raw_witness_count=0,
        effective_independent_count=0,
        in_band_count=0,
        outside_count=0,
        pending_count=0,
        max_gap_bps=None,
        mutual_spread_bps=None,
        classifications=(),
    )

    payload = build_market_fabric_operator_snapshot(
        rows={"btc_usd": (executable, intelligence, None)}
    )
    row = payload["instruments"][0]

    assert row["executable"]["bid"] is None
    assert row["executable"]["ask"] is None
    assert row["intelligence"]["max_gap_bps"] is None
    assert row["microstructure"] is None
