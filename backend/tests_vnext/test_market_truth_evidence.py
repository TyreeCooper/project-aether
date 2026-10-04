from __future__ import annotations

from datetime import datetime, timezone

from aether_vnext.market_truth_contract import EvidenceState, ExecutionState, ProviderRole
from aether_vnext.market_truth_evidence import WitnessObservation, build_evidence_snapshot, corroborated_badge
from aether_vnext.market_truth_fabric import ExecutableBookSnapshot
from aether_vnext.market_truth_provider import ProviderCard, ProviderCardRegistry, ProviderFeeSchedule
from aether_vnext.market_truth_route import RouteRecord


NOW = datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc)


def _providers() -> ProviderCardRegistry:
    return ProviderCardRegistry((
        ProviderCard("kraken", ProviderRole.BOTH, "Kraken", ProviderFeeSchedule("kraken"), "public_book;paper_only"),
        ProviderCard("coinbase", ProviderRole.OBSERVE, "Coinbase", ProviderFeeSchedule("none"), "public_market_data"),
        ProviderCard("gemini", ProviderRole.OBSERVE, "Gemini", ProviderFeeSchedule("none"), "public_market_data"),
    ))


def _route(witnesses=("coinbase", "gemini")) -> RouteRecord:
    return RouteRecord(
        "btc-usd", "kraken", witnesses, "operator", NOW, 1
    )


def _exec(state=ExecutionState.EXECUTABLE) -> ExecutableBookSnapshot:
    values = dict(
        canonical_instrument_id="btc-usd",
        route_id=_route().route_id,
        executable_provider_id="kraken",
        venue="Kraken",
        transport_id="kraken-ws",
        state=state,
        bid=100.0,
        ask=101.0,
        last_if_printed=100.5,
        bid_size=1.0,
        ask_size=1.0,
        venue_time_utc=NOW,
        receive_time_utc=NOW,
        state_reason="fresh",
    )
    if state is not ExecutionState.EXECUTABLE:
        values.update(
            bid=None, ask=None, last_if_printed=None, bid_size=None, ask_size=None
        )
    return ExecutableBookSnapshot(**values)


def _witness(provider: str, venue: str, bid: float, ask: float) -> WitnessObservation:
    return WitnessObservation(
        "btc-usd", provider, venue, bid, ask, None, NOW, NOW
    )


def test_no_witness_is_distinct_from_execution_not_observed() -> None:
    route = _route(())
    evidence = build_evidence_snapshot(
        route, _exec(), (), providers=_providers(), as_of_utc=NOW,
        max_witness_age_ms=2000, divergence_bps=25.0,
    )
    assert evidence.state is EvidenceState.NO_WITNESS
    assert evidence.authority == "NON_EXECUTABLE"


def test_witness_one_percent_away_changes_evidence_not_executable_price() -> None:
    executable = _exec()
    before = (executable.bid, executable.ask)
    evidence = build_evidence_snapshot(
        _route(),
        executable,
        (
            _witness("coinbase", "Coinbase", 101.0, 102.01),
            _witness("gemini", "Gemini", 100.02, 101.02),
        ),
        providers=_providers(),
        as_of_utc=NOW,
        max_witness_age_ms=2000,
        divergence_bps=25.0,
    )
    assert evidence.state is EvidenceState.DIVERGED
    assert evidence.max_gap_bps_to_executable is not None
    assert (executable.bid, executable.ask) == before


def test_multiple_close_public_witnesses_can_be_full() -> None:
    evidence = build_evidence_snapshot(
        _route(),
        _exec(),
        (
            _witness("coinbase", "Coinbase", 100.01, 101.01),
            _witness("gemini", "Gemini", 99.99, 100.99),
        ),
        providers=_providers(),
        as_of_utc=NOW,
        max_witness_age_ms=2000,
        divergence_bps=25.0,
    )
    assert evidence.state is EvidenceState.FULL
    assert corroborated_badge(_exec(), evidence) is True


def test_healthy_witnesses_do_not_restore_dead_executable_book() -> None:
    dead = _exec(ExecutionState.NOT_OBSERVED)
    evidence = build_evidence_snapshot(
        _route(),
        dead,
        (
            _witness("coinbase", "Coinbase", 100.0, 101.0),
            _witness("gemini", "Gemini", 100.01, 101.01),
        ),
        providers=_providers(),
        as_of_utc=NOW,
        max_witness_age_ms=2000,
        divergence_bps=25.0,
    )
    assert evidence.state is EvidenceState.FULL
    assert dead.state is ExecutionState.NOT_OBSERVED
    assert dead.bid is None and dead.ask is None
    assert corroborated_badge(dead, evidence) is False
