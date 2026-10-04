from __future__ import annotations

from pathlib import Path

from aether_vnext.canonical_pipeline import (
    CANONICAL_GATES,
    build_canonical_gate_snapshot,
)
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY


ROOT = Path(__file__).resolve().parents[2]


def test_full_pipeline_contract_keeps_market_fabric_and_history_authorities_separate() -> None:
    supervisor = (
        ROOT / "backend" / "aether_vnext" / "prototype_strategy_supervisor.py"
    ).read_text(encoding="utf-8")
    source_pool = (
        ROOT / "backend" / "aether_vnext" / "prototype_history_source_pool.py"
    ).read_text(encoding="utf-8")

    assert "fetch_historical_reference_pool" in supervisor
    assert "REFERENCE_SOURCE_IDS" in supervisor
    assert '"authority": "market_fabric_v3"' in supervisor
    assert '"consensus_can_replace_executable_price": False' in supervisor
    assert '"history_service_failover_active"' in supervisor
    assert '"isolated_asset_failures"' in supervisor
    assert "build_canonical_gate_snapshot" in supervisor

    # Legacy providers may exist inside the source pool as tiered historical
    # fallbacks, but they must never be direct strategy-supervisor dependencies.
    assert "fetch_coinbase_hourly_history" not in supervisor
    assert "fetch_coinbase_public_products" not in supervisor
    assert "fetch_coinbase_hourly_history" in source_pool
    assert "fetch_cryptocompare_kraken_hourly" in source_pool


def test_canonical_pipeline_reconciles_history_holds_without_stopping_other_assets() -> None:
    pipeline = {
        "focus_admitted": 4,
        "dynamic_kraken_available": 4,
        "roaming_batch": 4,
        "market_ready": 3,
        "market_not_ready": 1,
        "history_ready": 2,
        "history_not_ready": 1,
        "strategy_evaluated": 2,
        "evaluation_error": 0,
    }
    dynamic = {
        "sol": {"stage": "WATCH"},
        "btc": {"stage": "NO_SETUP"},
        "xdp": {"stage": "INSUFFICIENT_HISTORY"},
        "dot": {"stage": "MARKET_NOT_READY"},
    }

    gates = build_canonical_gate_snapshot(
        pipeline=pipeline,
        dynamic_results=dynamic,
        exit_results={},
        registry_status={"received": 4, "persisted": 4},
    )
    by_number = {row["number"]: row for row in gates}

    assert by_number[4]["input"] == 4
    assert by_number[4]["pass"] == 3
    assert by_number[4]["hold"] == 1
    assert by_number[5]["input"] == 3
    assert by_number[5]["pass"] == 2
    assert by_number[5]["hold"] == 1
    assert by_number[6]["input"] == 2
    assert by_number[6]["pass"] == 2
    assert by_number[7]["hold"] == 1
    assert by_number[8]["input"] == 1
    assert by_number[8]["hold"] == 1


def test_canonical_pipeline_is_exactly_seventeen_gates_and_live_stays_blocked() -> None:
    assert tuple(number for number, _, _ in CANONICAL_GATES) == tuple(range(1, 18))
    assert CANONICAL_GATES[3][2] == "Executable Ingress"
    assert CANONICAL_GATES[4][2] == "History & Warm-Up"
    assert CANONICAL_GATES[-1][2] == "Close Fill"
    assert PAPER_ONLY is True
    assert LIVE_BLOCKED is True


def test_round_trip_contract_exists_for_open_through_flat() -> None:
    round_trip = (
        ROOT / "backend" / "tests_vnext" / "test_runtime_round_trip.py"
    ).read_text(encoding="utf-8")
    for token in (
        "reserve_runtime_ready_ticket(",
        "submit_runtime_reserved_open(",
        "fill_runtime_submitted_open(",
        "request_runtime_flatten(",
        "reserve_runtime_flatten(",
        "submit_runtime_reserved_close(",
        "fill_runtime_submitted_close(",
        'assert flat["state"] == "FLAT"',
    ):
        assert token in round_trip
