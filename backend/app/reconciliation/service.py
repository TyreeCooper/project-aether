"""Position reconciliation primitives.

The current paper deployment compares local state with an injected venue/account
snapshot provider. Future live adapters can use the same contract without
changing the reconciliation policy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconcileDecision:
    ok: bool
    local_btc: float
    venue_btc: float
    delta_btc: float
    tolerance_btc: float
    reason: str


class ReconciliationService:
    def __init__(self, *, tolerance_btc: float = 1e-8) -> None:
        if tolerance_btc < 0:
            raise ValueError("tolerance_btc must be non-negative")
        self.tolerance_btc = tolerance_btc

    def compare_position(
        self,
        *,
        local_btc: float,
        venue_btc: float,
    ) -> ReconcileDecision:
        delta = venue_btc - local_btc
        ok = abs(delta) <= self.tolerance_btc
        return ReconcileDecision(
            ok=ok,
            local_btc=local_btc,
            venue_btc=venue_btc,
            delta_btc=delta,
            tolerance_btc=self.tolerance_btc,
            reason="matched" if ok else "position_mismatch",
        )
