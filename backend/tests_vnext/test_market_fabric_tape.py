from __future__ import annotations

from aether_vnext.market_fabric_tape import (
    EvidenceState,
    ExecutableTapeSnapshot,
    ExecutionState,
    WitnessClass,
    WitnessEvidencePolicy,
    WitnessObservation,
    build_aether_tape_snapshot,
)


POLICY = WitnessEvidencePolicy(
    required_effective_groups=3,
    max_alignment_ms=250,
    base_band_bps=5.0,
    c_vol=2.0,
    band_cap_bps=25.0,
    persistence_evaluations=3,
    hard_gap_multiple=10.0,
    contested_ratio=0.5,
    mutual_band_multiple=2.0,
    basis_cap_bps=10.0,
)


def _exec() -> ExecutableTapeSnapshot:
    return ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-usd-paper",
        authorized_economic_source_id="kraken_spot",
        state=ExecutionState.EXECUTABLE,
        bid=100000.0,
        ask=100002.0,
        last_if_printed=100001.0,
        last_credible_age_ms=25,
    )


def _witness(name: str, group: str, mid: float, **kwargs) -> WitnessObservation:
    spread = 2.0
    return WitnessObservation(
        witness_id=name,
        economic_source_id=name,
        independence_group_id=group,
        bid=mid - 1.0,
        ask=mid + 1.0,
        age_ms=20,
        alignment_delta_ms=10,
        spread_bps=spread / mid * 10000.0,
        **kwargs,
    )


def test_witness_divergence_cannot_move_executable_bid_or_ask() -> None:
    executable = _exec()
    tape = build_aether_tape_snapshot(
        executable,
        (
            _witness(
                "coinbase",
                "venue:coinbase",
                101500.0,
                outside_band_evaluations=3,
            ),
            _witness("gemini", "venue:gemini", 100001.0),
            _witness("bitstamp", "venue:bitstamp", 100001.5),
        ),
        policy=POLICY,
        realized_vol_bps=1.0,
        max_witness_age_ms=1000,
    )

    assert tape.executable.bid == 100000.0
    assert tape.executable.ask == 100002.0
    assert tape.intelligence.evidence_state in {
        EvidenceState.DIVERGED,
        EvidenceState.CONTESTED,
    }
    assert tape.intelligence.outside_count == 1


def test_three_independent_in_band_groups_reach_full() -> None:
    tape = build_aether_tape_snapshot(
        _exec(),
        (
            _witness("coinbase", "venue:coinbase", 100001.0),
            _witness("gemini", "venue:gemini", 100001.5),
            _witness("bitstamp", "venue:bitstamp", 100000.5),
        ),
        policy=POLICY,
        realized_vol_bps=1.0,
        max_witness_age_ms=1000,
    )

    assert tape.intelligence.evidence_state is EvidenceState.FULL
    assert tape.intelligence.quorum_met is True
    assert tape.intelligence.effective_independent_count == 3


def test_two_transports_in_same_independence_group_count_once() -> None:
    tape = build_aether_tape_snapshot(
        _exec(),
        (
            _witness("coinbase-direct", "venue:coinbase", 100001.0),
            _witness("vendor-x-coinbase", "venue:coinbase", 100001.1),
            _witness("gemini", "venue:gemini", 100001.5),
        ),
        policy=POLICY,
        realized_vol_bps=1.0,
        max_witness_age_ms=1000,
    )

    assert tape.intelligence.raw_witness_count == 3
    assert tape.intelligence.effective_independent_count == 2
    assert tape.intelligence.evidence_state is EvidenceState.DEGRADED


def test_alignment_failure_is_rejected_not_false_divergence() -> None:
    late = _witness("coinbase", "venue:coinbase", 99500.0)
    late = WitnessObservation(
        witness_id=late.witness_id,
        economic_source_id=late.economic_source_id,
        independence_group_id=late.independence_group_id,
        bid=late.bid,
        ask=late.ask,
        age_ms=late.age_ms,
        alignment_delta_ms=251,
        spread_bps=late.spread_bps,
    )
    tape = build_aether_tape_snapshot(
        _exec(),
        (late,),
        policy=POLICY,
        realized_vol_bps=1.0,
        max_witness_age_ms=1000,
    )

    classification = tape.intelligence.classifications[0]
    assert classification.classification is WitnessClass.REJECTED
    assert classification.reason == "alignment_exceeded"
    assert tape.intelligence.evidence_state is EvidenceState.NOT_OBSERVED


def test_non_executable_book_blanks_price_and_closes_evidence_reference() -> None:
    stale = ExecutableTapeSnapshot(
        instrument_id="btc_usd",
        route_id="btc-usd-paper",
        authorized_economic_source_id="kraken_spot",
        state=ExecutionState.STALE,
        bid=None,
        ask=None,
        last_if_printed=100001.0,
        last_credible_age_ms=5000,
    )
    tape = build_aether_tape_snapshot(
        stale,
        (_witness("coinbase", "venue:coinbase", 100001.0),),
        policy=POLICY,
        realized_vol_bps=1.0,
        max_witness_age_ms=1000,
    )

    assert tape.executable.bid is None
    assert tape.executable.ask is None
    assert tape.intelligence.evidence_state is EvidenceState.NOT_OBSERVED
