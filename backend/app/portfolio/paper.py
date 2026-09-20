"""In-memory paper portfolio with fee-aware cost basis.

Durable persistence is a later milestone; this module isolates accounting from
the engine now so PostgreSQL can replace the storage mechanism without changing
strategy or execution contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.execution import ExecutionResult


@dataclass(frozen=True)
class PortfolioSnapshot:
    usd: float
    btc: float
    equity: float
    avg_entry: float
    open_pnl: float
    realized_session: float
    daily_realized: float
    gross_realized: float
    total_fees: float
    total_spread_cost: float
    total_slippage_cost: float
    peak_equity: float


class PaperPortfolio:
    def __init__(self, starting_usd: float) -> None:
        if starting_usd <= 0:
            raise ValueError("starting_usd must be positive")
        self.usd = float(starting_usd)
        self.btc = 0.0
        self.avg_entry = 0.0  # all-in entry cost basis per BTC, including entry fees
        self.realized_session = 0.0
        self.daily_realized = 0.0
        self.gross_realized = 0.0
        self.total_fees = 0.0
        self.total_spread_cost = 0.0
        self.total_slippage_cost = 0.0
        self.peak_equity = float(starting_usd)
        self._daily_date = datetime.now(timezone.utc).date()

    def _roll_daily_if_needed(self, now: datetime | None = None) -> None:
        current_date: date = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        if current_date != self._daily_date:
            self.daily_realized = 0.0
            self._daily_date = current_date

    def equity(self, mark: float | None) -> float:
        return self.usd + self.btc * (mark or 0.0)

    def open_pnl(self, mark: float | None) -> float:
        if self.btc <= 0 or mark is None:
            return 0.0
        return (mark - self.avg_entry) * self.btc

    def mark_to_market(self, mark: float | None) -> None:
        self._roll_daily_if_needed()
        self.peak_equity = max(self.peak_equity, self.equity(mark))

    def snapshot(self, mark: float | None) -> PortfolioSnapshot:
        self._roll_daily_if_needed()
        return PortfolioSnapshot(
            usd=round(self.usd, 2),
            btc=self.btc,
            equity=round(self.equity(mark), 2),
            avg_entry=self.avg_entry,
            open_pnl=round(self.open_pnl(mark), 2),
            realized_session=round(self.realized_session, 2),
            daily_realized=round(self.daily_realized, 2),
            gross_realized=round(self.gross_realized, 2),
            total_fees=round(self.total_fees, 2),
            total_spread_cost=round(self.total_spread_cost, 2),
            total_slippage_cost=round(self.total_slippage_cost, 2),
            peak_equity=round(self.peak_equity, 2),
        )

    def apply_fill(self, fill: ExecutionResult, mark: float | None) -> tuple[bool, str | None]:
        self._roll_daily_if_needed()
        qty = fill.qty
        price = fill.execution_price
        fee = fill.fee_usd

        if qty <= 0:
            return False, "invalid_qty"

        if fill.side == "buy":
            all_in_cost = price * qty + fee
            if all_in_cost > self.usd + 1e-12:
                return False, "insufficient_usd"

            new_qty = self.btc + qty
            prior_cost_basis = self.avg_entry * self.btc
            self.avg_entry = (prior_cost_basis + all_in_cost) / new_qty
            self.usd -= all_in_cost
            self.btc = new_qty
        else:
            qty = min(qty, self.btc)
            if qty <= 0:
                return False, "no_inventory"

            gross_pnl = (price - self.avg_entry) * qty
            net_pnl = gross_pnl - fee
            proceeds = price * qty - fee

            self.usd += proceeds
            self.btc -= qty
            self.gross_realized += gross_pnl
            self.realized_session += net_pnl
            self.daily_realized += net_pnl

            if self.btc <= 1e-12:
                self.btc = 0.0
                self.avg_entry = 0.0

        self.total_fees += fee
        self.total_spread_cost += fill.spread_cost_usd
        self.total_slippage_cost += fill.slippage_cost_usd
        self.mark_to_market(mark)
        return True, None
