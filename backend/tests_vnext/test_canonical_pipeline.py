from __future__ import annotations

from aether_vnext.canonical_pipeline import (
    CANONICAL_GATES,
    build_canonical_gate_snapshot,
)


def test_canonical_backend_gate_contract_is_exactly_1_through_17() -> None:
    assert tuple(row[0] for row in CANONICAL_GATES) == tuple(range(1, 18))
    assert CANONICAL_GATES[-1][2] == "Close Fill"


def test_gate_snapshot_uses_observed_counts_without_inventing_transition_queues() -> None:
    pipeline = {
        "focus_admitted": 5,
        "dynamic_kraken_available": 5,
        "roaming_batch": 5,
        "market_ready": 4,
        "market_not_ready": 1,
        "history_ready": 3,
        "history_not_ready": 1,
        "strategy_evaluated": 3,
        "evaluation_error": 0,
    }
    dynamic = {
        "sol": {"stage": "WATCH"},
        "eth": {"stage": "SUBMITTED"},
        "btc": {"stage": "NO_SETUP"},
        "xdp": {"stage": "MARKET_NOT_READY"},
    }
    exits = {
        "eth": {"stage": "CLOSE_SUBMITTED"},
        "btc": {"stage": "FLAT"},
        "sol": {"stage": "OPEN"},
    }
    gates = build_canonical_gate_snapshot(
        pipeline=pipeline,
        dynamic_results=dynamic,
        exit_results=exits,
        registry_status={"received": 5, "persisted": 5},
    )
    by_number = {row["number"]: row for row in gates}

    assert by_number[4]["input"] == 5
    assert by_number[4]["pass"] == 4
    assert by_number[4]["hold"] == 1
    assert by_number[5]["pass"] == 3
    assert by_number[7]["hold"] == 1
    assert by_number[8]["input"] == 2
    assert by_number[8]["pass"] == 1
    assert by_number[12]["pass"] == 1
    assert by_number[13]["hold"] == 1
    assert by_number[15]["observability"] == "CUMULATIVE"
    assert by_number[16]["observability"] == "CUMULATIVE"
    assert by_number[17]["input"] == 2
    assert by_number[17]["pass"] == 1
    assert by_number[17]["hold"] == 1


def test_unobserved_discovery_input_stays_none() -> None:
    gates = build_canonical_gate_snapshot(
        pipeline={},
        dynamic_results={},
        exit_results={},
        registry_status={},
    )
    assert gates[0]["input"] is None
    assert gates[0]["observability"] == "PARTIAL"
