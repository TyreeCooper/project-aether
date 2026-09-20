"""In-memory paper portfolio with explicit execution-cost attribution.

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
    max_drawdown_pct: float
    closed_trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float | None
    avg_winner: float | None
    avg_loser: float | None


class PaperPortfolio:
    def __init__(self, starting_usd: float) -> None:
        if starting_usd <= 0:
            raise ValueError("starting_usd must be positive")

        self.usd = float(starting_usd)
        self.btc = 0.0
        self.avg_entry = 0.0
        self.entry_fees_open = 0.0

        self.realized_session = 0.0
        self.daily_realized = 0.0
        self.gross_realized = 0.0
        self.total_fees = 0.0
        self.total_spread_cost = 0.0
        self.total_slippage_cost = 0.0

        self.peak_equity = float(starting_usd)
        self.max_drawdown_pct = 0.0
        self.closed_trade_pnls: list[float] = []
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
        gross = (mark - self.avg_entry) * self.btc
        return gross - self.entry_fees_open

    def mark_to_market(self, mark: float | None) -> None:
        self._roll_daily_if_needed()
        equity = self.equity(mark)
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity * 100.0
            self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown)

    def _trade_stats(self) -> tuple[int, int, int, float | None, float | None, float | None]:
        wins = [p for p in self.closed_trade_pnls if p > 0]
        losses = [p for p in self.closed_trade_pnls if p < 0]
        count = len(self.closed_trade_pnls)
        win_rate = (len(wins) / count * 100.0) if count else None
        avg_winner = (sum(wins) / len(wins)) if wins else None
        avg_loser = (sum(losses) / len(losses)) if losses else None
        return count, len(wins), len(losses), win_rate, avg_winner, avg_loser

    def restore(
        self,
        *,
        usd: float,
        btc: float,
        avg_entry: float,
        entry_fees_open: float,
        realized_session: float,
        daily_realized: float,
        gross_realized: float,
        total_fees: float,
        total_spread_cost: float,
        total_slippage_cost: float,
        peak_equity: float,
        max_drawdown_pct: float,
        captured_at: datetime,
        closed_trade_pnls: list[float] | None = None,
        mark: float | None = None,
    ) -> None:
        self.usd = float(usd)
        self.btc = float(btc)
        self.avg_entry = float(avg_entry)
        self.entry_fees_open = float(entry_fees_open)
        self.realized_session = float(realized_session)
        self.gross_realized = float(gross_realized)
        self.total_fees = float(total_fees)
        self.total_spread_cost = float(total_spread_cost)
        self.total_slippage_cost = float(total_slippage_cost)
        self.peak_equity = float(peak_equity)
        self.max_drawdown_pct = float(max_drawdown_pct)
        self.closed_trade_pnls = list(closed_trade_pnls or [])

        today = datetime.now(timezone.utc).date()
        captured_date = captured_at.astimezone(timezone.utc).date()
        self.daily_realized = float(daily_realized) if captured_date == today else 0.0
        self._daily_date = today
        self.mark_to_market(mark)

    def snapshot(self, mark: float | None) -> PortfolioSnapshot:
        self._roll_daily_if_needed()
        self.mark_to_market(mark)
        count, wins, losses, win_rate, avg_winner, avg_loser = self._trade_stats()

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
            max_drawdown_pct=round(self.max_drawdown_pct, 4),
            closed_trade_count=count,
            winning_trades=wins,
            losing_trades=losses,
            win_rate_pct=round(win_rate, 2) if win_rate is not None else None,
            avg_winner=round(avg_winner, 2) if avg_winner is not None else None,
            avg_loser=round(avg_loser, 2) if avg_loser is not None else None,
        )

    def apply_fill(
        self,
        fill: ExecutionResult,
        mark: float | None,
    ) -> tuple[bool, str | None, float | None]:
        self._roll_daily_if_needed()
        qty = fill.qty
        price = fill.execution_price
        fee = fill.fee_usd

        if qty <= 0:
            return False, "invalid_qty", None

        realized_net: float | None = None

        if fill.side == "buy":
            all_in_cost = price * qty + fee
            if all_in_cost > self.usd + 1e-12:
                return False, "insufficient_usd", None

            new_qty = self.btc + qty
            prior_price_basis = self.avg_entry * self.btc
            self.avg_entry = (prior_price_basis + price * qty) / new_qty
            self.entry_fees_open += fee
            self.usd -= all_in_cost
            self.btc = new_qty

        else:
            qty = min(qty, self.btc)
            if qty <= 0:
                return False, "no_inventory", None

            prior_qty = self.btc
            fee_fraction = qty / prior_qty
            allocated_entry_fee = self.entry_fees_open * fee_fraction

            gross_pnl = (price - self.avg_entry) * qty
            realized_net = gross_pnl - allocated_entry_fee - fee
            proceeds = price * qty - fee

            self.usd += proceeds
            self.btc -= qty
            self.entry_fees_open -= allocated_entry_fee
            self.gross_realized += gross_pnl
            self.realized_session += realized_net
            self.daily_realized += realized_net
            self.closed_trade_pnls.append(realized_net)

            if self.btc <= 1e-12:
                self.btc = 0.0
                self.avg_entry = 0.0
                self.entry_fees_open = 0.0

        self.total_fees += fee
        self.total_spread_cost += fill.spread_cost_usd
        self.total_slippage_cost += fill.slippage_cost_usd
        self.mark_to_market(mark)
        return True, None, realized_net
