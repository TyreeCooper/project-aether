"""Institutional gate reconciliation contract for AETHER vNext.

Counts are emitted only for FULL coverage. PARTIAL coverage preserves unknowns as
None so operator surfaces cannot turn missing telemetry into zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

GATE_NAMES = (
    "CATALOG", "ELIGIBILITY", "PRIORITY", "BIND", "MARKET", "HISTORY",
    "EVALUATE", "SCOUT", "SNIPER", "ALLOCATOR", "RISK", "CLERK",
    "GOVERNOR", "PORTFOLIO", "PAPER_SUBMIT", "FILL", "POSITION", "EXIT",
)

@dataclass(frozen=True, slots=True)
class GateReconciliation:
    gate: str
    coverage: str
    input_count: int | None = None
    pass_count: int | None = None
    wait_count: int | None = None
    terminal_count: int | None = None
    fault_count: int | None = None
    unexplained_count: int | None = None
    telemetry_state: str = "EXPOSED"

    def __post_init__(self) -> None:
        if self.gate not in GATE_NAMES:
            raise ValueError("unknown institutional gate")
        if self.coverage not in {"FULL", "PARTIAL"}:
            raise ValueError("coverage must be FULL or PARTIAL")
        values = (self.input_count, self.pass_count, self.wait_count, self.terminal_count, self.fault_count, self.unexplained_count)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("gate counts cannot be negative")
        if self.coverage == "PARTIAL" and self.telemetry_state == "EXPOSED":
            object.__setattr__(self, "telemetry_state", "NOT_EXPOSED_BY_TELEMETRY")
        if self.coverage == "FULL":
            if any(value is None for value in values):
                raise ValueError("FULL coverage requires every count")
            assert self.input_count is not None
            accounted = sum((self.pass_count or 0, self.wait_count or 0, self.terminal_count or 0, self.fault_count or 0, self.unexplained_count or 0))
            if accounted != self.input_count:
                raise ValueError("FULL gate counts must reconcile to input")

def institutional_gate_book(observed: Mapping[str, GateReconciliation]) -> tuple[GateReconciliation, ...]:
    """Return all 18 gates in canonical order; absent telemetry remains unknown."""
    return tuple(
        observed.get(gate) or GateReconciliation(gate=gate, coverage="PARTIAL")
        for gate in GATE_NAMES
    )
