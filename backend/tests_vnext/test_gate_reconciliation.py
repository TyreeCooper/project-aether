from __future__ import annotations

import pytest

from aether_vnext.gate_reconciliation import GATE_NAMES, GateReconciliation, institutional_gate_book


def test_full_gate_must_reconcile() -> None:
    gate = GateReconciliation(gate="MARKET", coverage="FULL", input_count=10, pass_count=6, wait_count=2, terminal_count=1, fault_count=1, unexplained_count=0)
    assert gate.pass_count == 6
    with pytest.raises(ValueError, match="reconcile"):
        GateReconciliation(gate="MARKET", coverage="FULL", input_count=10, pass_count=6, wait_count=2, terminal_count=0, fault_count=0, unexplained_count=0)


def test_partial_gate_never_fabricates_zero_counts() -> None:
    book = institutional_gate_book({})
    assert len(book) == 18
    assert tuple(row.gate for row in book) == GATE_NAMES
    assert all(row.coverage == "PARTIAL" for row in book)
    assert all(row.pass_count is None for row in book)
    assert all(row.telemetry_state == "NOT_EXPOSED_BY_TELEMETRY" for row in book)


def test_observed_full_gate_is_preserved_among_unknown_gates() -> None:
    market = GateReconciliation(gate="MARKET", coverage="FULL", input_count=3, pass_count=1, wait_count=1, terminal_count=1, fault_count=0, unexplained_count=0)
    book = institutional_gate_book({"MARKET": market})
    assert book[GATE_NAMES.index("MARKET")] is market
    assert book[GATE_NAMES.index("RISK")].input_count is None
