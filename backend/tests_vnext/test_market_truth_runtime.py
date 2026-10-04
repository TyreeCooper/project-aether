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


def test_runtime_projection_is_five_layer_market_truth_not_legacy_tape_compatibility() -> None:
    universe = AssetUniverse((
        AssetUniverseRow("btc-usd", "spot_crypto", 0.1, 0.0001, "crypto_24x7"),
    ))
    providers = first_proof_provider_cards()
    route = first_proof_route(human_set_by="operator", set_at_utc=NOW)
    book = ExecutableBookSnapshot(
        canonical_instrument_id="btc-usd",
        route_id=route.route_id,
        executable_provider_id="kraken",
        venue="Kraken",
        transport_id="kraken-public-ws-v2-primary",
        state=ExecutionState.EXECUTABLE,
        bid=100.0,
        ask=101.0,
        last_if_printed=100.4,
        bid_size=1.0,
        ask_size=2.0,
        venue_time_utc=NOW,
        receive_time_utc=NOW,
        state_reason="fresh_coherent_route_book",
    )
    evidence = EvidenceSnapshot(
        canonical_instrument_id="btc-usd",
        route_id=route.route_id,
        state=EvidenceState.SINGLE_SOURCE,
        configured_witness_count=1,
        observed_witness_count=1,
        fresh_coherent_witness_count=1,
        assessments=(),
        max_gap_bps_to_executable=2.0,
    )
    payload = build_market_truth_snapshot(
        universe=universe,
        providers=providers,
        route=route,
        book=book,
        evidence=evidence,
        runtime_status={"running": True},
    )
    assert payload["architecture"] == "AETHER_MARKET_TRUTH_V1"
    assert tuple(payload["layers"]) == (
        "asset_universe", "provider_card", "route", "market_fabric", "execution"
    )
    assert payload["execution_universe"]["commissioned_count"] == 1
    assert payload["execution_universe"]["quoted_count"] == 1
    assert payload["first_proof"]["passed"] is False
    row = payload["instruments"][0]
    assert row["executable"]["bid"] == 100.0
    assert row["executable"]["ask"] == 101.0
    assert row["intelligence"]["evidence_state"] == "SINGLE_SOURCE"
    assert row["intelligence"]["derived_reference_executable"] is False


def test_dead_executable_book_stays_blank_even_if_evidence_full() -> None:
    universe = AssetUniverse((
        AssetUniverseRow("btc-usd", "spot_crypto", 0.1, 0.0001, "crypto_24x7"),
    ))
    providers = first_proof_provider_cards()
    route = first_proof_route(human_set_by="operator", set_at_utc=NOW)
    dead = ExecutableBookSnapshot.not_observed(
        route, venue="Kraken", reason="socket_down"
    )
    evidence = EvidenceSnapshot(
        canonical_instrument_id="btc-usd",
        route_id=route.route_id,
        state=EvidenceState.FULL,
        configured_witness_count=1,
        observed_witness_count=1,
        fresh_coherent_witness_count=1,
        assessments=(),
        max_gap_bps_to_executable=None,
    )
    payload = build_market_truth_snapshot(
        universe=universe,
        providers=providers,
        route=route,
        book=dead,
        evidence=evidence,
        runtime_status={"running": True},
    )
    executable = payload["instruments"][0]["executable"]
    assert executable["state"] == "NOT_OBSERVED"
    assert executable["bid"] is None
    assert executable["ask"] is None
    assert payload["instruments"][0]["intelligence"]["evidence_state"] == "FULL"


def test_market_truth_runtime_bootstrap_uses_identity_facts_not_full_ticker_universe() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = (root / "backend" / "aether_vnext" / "market_truth_runtime.py").read_text(encoding="utf-8")
    catalog = (root / "backend" / "aether_vnext" / "kraken_catalog.py").read_text(encoding="utf-8")
    assert "fetch_kraken_spot_pair_facts" in runtime
    assert "fetch_kraken_discovery_universe" not in runtime
    assert "asyncio.wait_for(" in runtime
    assert "ASSET_PAIRS_PATH" in catalog
    assert "Market Truth bootstrap needs\n    no prices here" in catalog
