"""In-process paper trading orchestrator.

Market data, execution, portfolio accounting, and profitability checks are
separate concerns. Live execution remains blocked.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.execution import ExecutionGateway, ExecutionResult, OrderRequest, PaperExecutionGateway
from app.market_data import CoinGeckoMarketDataProvider, MarketDataProvider
from app.portfolio import PaperPortfolio
from app.profitability import ProfitabilityDecision, ProfitabilityGate, StaticCostModel
from app.risk import deny_entry
from app.strategy import crossover_signal, sma

STARTING_USD = 10_000.0
TAKER_FEE = 0.0026
PAPER_SPREAD_BPS = 0.0
PAPER_SLIPPAGE_BPS = 0.0
MIN_EDGE_MULTIPLE = 1.25
POLL_SECONDS = 15
SHORT_MA = 8
LONG_MA = 21
STOP_LOSS_PCT = 2.0
POSITION_BTC = 0.01
MAX_POSITION_BTC = 0.02
MAX_DRAWDOWN_PCT = 8.0
DAILY_LOSS_CAP = 250.0
SYMBOL = "BTC/USD"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperEngine:
    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        execution: ExecutionGateway | None = None,
        portfolio: PaperPortfolio | None = None,
        profitability_gate: ProfitabilityGate | None = None,
    ) -> None:
        self.paper_mode = True
        self.live_blocked = True
        self.state = "OFFLINE"
        self.flatten_lock = False
        self.symbol = SYMBOL

        self.market_data = market_data or CoinGeckoMarketDataProvider()
        self.execution = execution or PaperExecutionGateway(
            taker_fee_rate=TAKER_FEE,
            spread_bps=PAPER_SPREAD_BPS,
            slippage_bps=PAPER_SLIPPAGE_BPS,
        )
        self.portfolio = portfolio or PaperPortfolio(starting_usd=STARTING_USD)
        self.profitability_gate = profitability_gate or ProfitabilityGate(
            StaticCostModel(
                taker_fee_rate=TAKER_FEE,
                spread_bps=PAPER_SPREAD_BPS,
                slippage_bps=PAPER_SLIPPAGE_BPS,
            ),
            minimum_edge_multiple=MIN_EDGE_MULTIPLE,
            enforce=False,
        )
        self.last_profitability: ProfitabilityDecision | None = None

        self.mark: float | None = None
        self.mark_source = "unavailable"
        self.last_tick_age_ms: int | None = None
        self._last_tick_mono: float | None = None
        self.closes: deque[float] = deque(maxlen=300)
        self.audit: deque[dict[str, Any]] = deque(maxlen=200)

        self.short_ma = SHORT_MA
        self.long_ma = LONG_MA
        self.stop_loss_pct = STOP_LOSS_PCT
        self.position_size = POSITION_BTC
        self.max_position = MAX_POSITION_BTC

        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._log("INFO", "Paper engine constructed. Bot OFFLINE. Live execution blocked.")

    def _log(self, level: str, message: str) -> None:
        self.audit.appendleft({"ts": _now(), "level": level, "message": message})

    @property
    def usd(self) -> float:
        return self.portfolio.usd

    @property
    def btc(self) -> float:
        return self.portfolio.btc

    @property
    def avg_entry(self) -> float:
        return self.portfolio.avg_entry

    @property
    def realized_session(self) -> float:
        return self.portfolio.realized_session

    @property
    def daily_realized(self) -> float:
        return self.portfolio.daily_realized

    @property
    def peak_equity(self) -> float:
        return self.portfolio.peak_equity

    @property
    def equity(self) -> float:
        return self.portfolio.equity(self.mark)

    @property
    def open_pnl(self) -> float:
        return self.portfolio.open_pnl(self.mark)

    def snapshot(self) -> dict[str, Any]:
        age = None
        if self._last_tick_mono is not None:
            age = int((time.monotonic() - self._last_tick_mono) * 1000)
            self.last_tick_age_ms = age

        short = sma(list(self.closes), self.short_ma)
        long = sma(list(self.closes), self.long_ma)
        p = self.portfolio.snapshot(self.mark)
        profitability = self.last_profitability

        return {
            "state": self.state,
            "paper_mode": self.paper_mode,
            "live_blocked": self.live_blocked,
            "flatten_lock": self.flatten_lock,
            "strategy": "sma_crossover",
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_btc": self.position_size,
            "bars": len(self.closes),
            "warm_up_needed": self.long_ma + 1,
            "short_value": short,
            "long_value": long,
            "mark": self.mark,
            "mark_source": self.mark_source,
            "last_tick_age_ms": age,
            "usd": p.usd,
            "btc": p.btc,
            "equity": p.equity,
            "avg_entry": p.avg_entry,
            "open_pnl": p.open_pnl,
            "realized_session": p.realized_session,
            "daily_realized": p.daily_realized,
            "gross_realized": p.gross_realized,
            "total_fees": p.total_fees,
            "total_spread_cost": p.total_spread_cost,
            "total_slippage_cost": p.total_slippage_cost,
            "peak_equity": p.peak_equity,
            "profitability_enforced": self.profitability_gate.enforce,
            "last_profitability_reason": profitability.reason if profitability else None,
            "last_expected_move_bps": profitability.expected_move_bps if profitability else None,
            "last_minimum_required_bps": (
                profitability.minimum_required_bps if profitability else None
            ),
            "reason": "Paper machine. Public SMA rule. Live execution blocked.",
        }

    async def seed_history(self) -> None:
        try:
            prices = await self.market_data.get_seed_prices(self.symbol, limit=120)
            for px in prices:
                self.closes.append(float(px))
            if self.closes:
                self.mark = self.closes[-1]
                self.mark_source = getattr(self.market_data, "source", "provider")
                self._last_tick_mono = time.monotonic()
                self.portfolio.mark_to_market(self.mark)
            self._log("INFO", f"Seeded {len(self.closes)} public BTC marks for SMA warm-up.")
        except Exception as exc:
            self._log("WARN", f"History seed failed: {exc}")

    def _apply_execution(self, fill: ExecutionResult, actor: str) -> bool:
        applied, error = self.portfolio.apply_fill(fill, self.mark)
        if not applied:
            self._log("WARN", f"Paper fill rejected by portfolio: {error}")
            return False

        if fill.side == "buy":
            self.state = "IN_POSITION"
        elif self.portfolio.btc <= 0:
            self.state = "IDLE" if self.state != "OFFLINE" else "OFFLINE"

        self._log(
            "FILL",
            (
                f"{actor} {fill.side.upper()} {fill.qty} BTC @ "
                f"{fill.execution_price:.2f} fee {fill.fee_usd:.2f} "
                f"spread_cost {fill.spread_cost_usd:.2f} "
                f"slippage_cost {fill.slippage_cost_usd:.2f} "
                f"client_order_id={fill.client_order_id}"
            ),
        )
        return True

    async def _execute(self, side: str, qty: float, actor: str) -> bool:
        if not self.mark:
            return False
        if side == "sell":
            qty = min(qty, self.btc)
            if qty <= 0:
                return False

        request = OrderRequest.market(
            side=side,  # type: ignore[arg-type]
            qty=qty,
            reference_price=self.mark,
            actor=actor,
        )
        fill = await self.execution.execute_market(request)
        return self._apply_execution(fill, actor)

    def _profitability_allows_entry(self, qty: float) -> bool:
        if not self.mark:
            return False

        # The reference SMA rule does not yet estimate forward move in bps.
        # In paper mode the gate is advisory until a strategy supplies that
        # estimate; the missing estimate is surfaced explicitly, not guessed.
        decision = self.profitability_gate.evaluate(
            qty=qty,
            reference_price=self.mark,
            expected_move_bps=None,
        )
        self.last_profitability = decision

        if not decision.allowed:
            self._log(
                "WARN",
                (
                    "Buy denied by profitability gate: "
                    f"{decision.reason}; required={decision.minimum_required_bps:.2f}bps"
                ),
            )
            return False

        if decision.reason == "expected_edge_unavailable":
            self._log(
                "INFO",
                (
                    "Profitability gate advisory only: expected edge unavailable; "
                    f"estimated one-way cost={decision.costs.total_cost_bps:.2f}bps"
                ),
            )
        return True

    async def evaluate_and_maybe_trade(self) -> None:
        if self.state not in ("IDLE", "IN_POSITION") or not self.mark:
            return

        if self.btc > 0 and self.avg_entry > 0:
            stop = self.avg_entry * (1 - self.stop_loss_pct / 100)
            if self.mark <= stop:
                self._log("BOT", f"Stop-loss hit at {self.mark:.2f} (stop {stop:.2f}).")
                await self._execute("sell", self.btc, "bot-stop")
                return

        signal = crossover_signal(
            list(self.closes),
            self.short_ma,
            self.long_ma,
            in_position=self.btc > 0,
        )

        if signal == "buy":
            if not self._profitability_allows_entry(self.position_size):
                return

            reason = deny_entry(
                flatten_lock=self.flatten_lock,
                paper_mode=self.paper_mode,
                live_blocked=self.live_blocked,
                qty=self.position_size,
                position_btc=self.btc,
                max_position_btc=self.max_position,
                equity=self.equity,
                peak_equity=self.peak_equity,
                max_drawdown_pct=MAX_DRAWDOWN_PCT,
                daily_realized=self.daily_realized,
                daily_loss_cap=DAILY_LOSS_CAP,
            )
            if reason:
                self._log("WARN", f"Buy denied: {reason}")
                return

            self._log("BOT", f"SMA cross-up. Paper BUY {self.position_size} BTC")
            await self._execute("buy", self.position_size, "bot")

        elif signal == "sell" and self.btc > 0:
            self._log("BOT", "SMA cross-down. Paper SELL inventory")
            await self._execute("sell", self.btc, "bot")

    async def tick(self) -> None:
        try:
            snapshot = await self.market_data.get_mark(self.symbol)
        except Exception as exc:
            self._log("WARN", f"Mark fetch failed: {exc}")
            return

        if snapshot is None:
            return

        async with self._lock:
            self.mark = snapshot.price
            self.mark_source = snapshot.source
            self.closes.append(snapshot.price)
            self._last_tick_mono = time.monotonic()
            self.portfolio.mark_to_market(self.mark)
            await self.evaluate_and_maybe_trade()

    async def loop(self) -> None:
        await self.seed_history()
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self._log("ERROR", f"Tick fault: {exc}")
            await asyncio.sleep(POLL_SECONDS)

    def start_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop())

    async def start_bot(self) -> dict[str, Any]:
        async with self._lock:
            if self.flatten_lock:
                return {"ok": False, "error": "flatten_lock"}
            self.state = "IN_POSITION" if self.btc > 0 else "IDLE"
            self._log("INFO", f"Bot armed ({self.state}).")
            return {"ok": True, **self.snapshot()}

    async def stop_bot(self) -> dict[str, Any]:
        async with self._lock:
            self.state = "OFFLINE"
            self._log("INFO", "Bot disarmed. Position left untouched.")
            return {"ok": True, **self.snapshot()}

    async def manual(self, side: str, qty: float | None = None) -> dict[str, Any]:
        async with self._lock:
            if not self.mark:
                return {"ok": False, "error": "no_mark"}

            qty = qty or self.position_size
            if side == "buy":
                reason = deny_entry(
                    flatten_lock=self.flatten_lock,
                    paper_mode=True,
                    live_blocked=True,
                    qty=qty,
                    position_btc=self.btc,
                    max_position_btc=self.max_position,
                    equity=self.equity,
                    peak_equity=self.peak_equity,
                    max_drawdown_pct=MAX_DRAWDOWN_PCT,
                    daily_realized=self.daily_realized,
                    daily_loss_cap=DAILY_LOSS_CAP,
                )
                if reason:
                    return {"ok": False, "error": reason}

            await self._execute(side, qty, "operator")
            return {"ok": True, **self.snapshot()}

    async def flatten(self) -> dict[str, Any]:
        async with self._lock:
            self.flatten_lock = True
            if self.btc > 0 and self.mark:
                await self._execute("sell", self.btc, "flatten")
            self.state = "OFFLINE"
            self._log("INFO", "Emergency flatten complete. Entries locked.")
            return {"ok": True, **self.snapshot()}

    async def unlock(self) -> dict[str, Any]:
        async with self._lock:
            self.flatten_lock = False
            self._log("INFO", "Flatten lock cleared by operator.")
            return {"ok": True, **self.snapshot()}


engine = PaperEngine()
