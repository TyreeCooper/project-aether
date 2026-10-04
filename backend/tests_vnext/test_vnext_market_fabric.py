from __future__ import annotations

from datetime import datetime, timezone

from aether_vnext.market_truth_contract import EvidenceState, ExecutionState
from aether_vnext.market_truth_evidence import EvidenceSnapshot
from aether_vnext.market_truth_fabric import ExecutableBookSnapshot
from aether_vnext.market_truth_first_proof import first_proof_provider_cards, first_proof_route
from aether_vnext.market_truth_runtime import build_market_truth_snapshot
from aether_vnext.market_truth_universe import AssetUniverse, AssetUniverseRow


UTC = timezone.utc
NOW = datetime(2026, 10, 4, 22, 0, tzinfo=UTC)


def _fixture(*, execution_state=ExecutionState.EXECUTABLE, evidence_state=EvidenceState.SINGLE_SOURCE):
    universe = AssetUniverse((
        AssetUniverseRow("btc-usd", "spot_crypto", 0.1, 0.0001, "crypto_24x7"),
    ))
    providers = first_proof_provider_cards()
    route = first_proof_route(human_set_by="operator", set_at_utc=NOW)
    if execution_state is ExecutionState.EXECUTABLE:
        book = ExecutableBookSnapshot(
            canonical_instrument_id="btc-usd",
            route_id=route.route_id,
            executable_provider_id="kraken",
            venue="Kraken",
            transport_id="kraken-public-ws-v2-primary",
            state=execution_state,
            bid=100.0,
            ask=101.0,
            last_if_printed=100.4,
            bid_size=1.0,
            ask_size=2.0,
            venue_time_utc=NOW,
            receive_time_utc=NOW,
            state_reason="fresh_coherent_route_book",
        )
    else:
        book = ExecutableBookSnapshot.not_observed(
            route, venue="Kraken", reason="socket_down"
        )
    evidence = EvidenceSnapshot(
        canonical_instrument_id="btc-usd",
        route_id=route.route_id,
        state=evidence_state,
        configured_witness_count=1,
        observed_witness_count=1 if evidence_state is not EvidenceState.NO_WITNESS else 0,
        fresh_coherent_witness_count=1 if evidence_state is not EvidenceState.NO_WITNESS else 0,
        assessments=(),
        max_gap_bps_to_executable=None,
    )
    return build_market_truth_snapshot(
        universe=universe,
        providers=providers,
        route=route,
        book=book,
        evidence=evidence,
        runtime_status={"running": True},
    )


def test_market_fabric_api_contract_is_canonical_five_layer_runtime() -> None:
    payload = _fixture()
    assert payload["architecture"] == "AETHER_MARKET_TRUTH_V1"
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["authority"]["witness_can_replace_executable_price"] is False
    assert payload["authority"]["automatic_execution_venue_switch_allowed"] is False
    assert payload["runtime_contract"]["missing_field_semantics"] == "NULL_NEVER_ZERO"
    assert "NO_WITNESS" in payload["runtime_contract"]["evidence_states"]
    assert "NOT_OBSERVED" not in payload["runtime_contract"]["evidence_states"]


def test_market_fabric_keeps_execution_and_evidence_axes_separate() -> None:
    payload = _fixture(
        execution_state=ExecutionState.NOT_OBSERVED,
        evidence_state=EvidenceState.FULL,
    )
    row = payload["instruments"][0]
    assert row["executable"]["state"] == "NOT_OBSERVED"
    assert row["executable"]["bid"] is None
    assert row["executable"]["ask"] is None
    assert row["intelligence"]["evidence_state"] == "FULL"
    assert row["intelligence"]["derived_reference_executable"] is False
