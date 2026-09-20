"""Application service that composes economic and safety entry gates."""

from __future__ import annotations

from dataclasses import dataclass

from app.profitability import ProfitabilityDecision, ProfitabilityGate
from app.risk import deny_entry


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    reason: str | None
    profitability: ProfitabilityDecision


class EntryDecisionService:
    def __init__(self, profitability_gate: ProfitabilityGate) -> None:
        self.profitability_gate = profitability_gate

    def evaluate(
        self,
        *,
        expected_move_bps: float | None,
        reference_price: float,
        qty: float,
        flatten_lock: bool,
        paper_mode: bool,
        live_blocked: bool,
        position_btc: float,
        max_position_btc: float,
        equity: float,
        peak_equity: float,
        max_drawdown_pct: float,
        daily_realized: float,
        daily_loss_cap: float,
    ) -> EntryDecision:
        profitability = self.profitability_gate.evaluate(
            qty=qty,
            reference_price=reference_price,
            expected_move_bps=expected_move_bps,
        )
        if not profitability.allowed:
            return EntryDecision(
                allowed=False,
                reason=profitability.reason,
                profitability=profitability,
            )

        risk_reason = deny_entry(
            flatten_lock=flatten_lock,
            paper_mode=paper_mode,
            live_blocked=live_blocked,
            qty=qty,
            position_btc=position_btc,
            max_position_btc=max_position_btc,
            equity=equity,
            peak_equity=peak_equity,
            max_drawdown_pct=max_drawdown_pct,
            daily_realized=daily_realized,
            daily_loss_cap=daily_loss_cap,
        )
        return EntryDecision(
            allowed=risk_reason is None,
            reason=risk_reason,
            profitability=profitability,
        )
