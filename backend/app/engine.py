"""In-process paper trading orchestrator.

Market-data transport and order execution are delegated to interfaces so the
same engine can later run against venue adapters without embedding HTTP or
fill mechanics here. Live execution remains blocked.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.execution import ExecutionResult, OrderRequest, PaperExecutionGateway
from app.market_data import CoinGeckoMarketDataProvider, MarketDataProvider
from app.risk import deny_entry
from app.strategy import crossover_signal, sma

STARTING_USD = 10_000.0
TAKER_FEE = 0.0026
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
        execution: PaperExecutionGateway | None = None,
    ) -> None:
        self.paper_mode = True
        self.live_blocked = True
        self.state = "OFFLINE"
        self.flatten_lock = False

        # Portfolio remains in-process for this milestone. It moves to the
        # dedicated portfolio/persistence layer in the next milestone.
        self.usd = STARTING_USD
        self.btc = 0.0
        self.avg_entry = 0.0
        self.realized_session = 0.0
        self.daily_realized = 0.0
        self.peak_equity = STARTING_USD

        self.symbol = SYMBOL
        self.market_data = market_data or CoinGeckoMarketDataProvider()
        self.execution = execution or PaperExecutionGateway(taker_fee_rate=TAKER_FEE)

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
    def equity(self) -> float:
        mark = self.mark or 0.0
        return self.usd + self.btc * mark

    @property
    def open_pnl(self) -> float:
        if self.btc <= 0 or not self.mark:
            return 0.0
        return (self.mark - self.avg_entry) * self.btc

    def snapshot(self) -> dict[str, Any]:
        age = None
        if self._last_tick_mono is not None:
            age = int((time.monotonic() - self._last_tick_mono) * 1000)
            self.last_tick_age_ms = age
        short = sma(list(self.closes), self.short_ma)
        long = sma(list(self.closes), self.long_ma)
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
            "usd": round(self.usd, 2),
            "btc": self.btc,
            "equity": round(self.equity, 2),
            "avg_entry": self.avg_entry,
            "open_pnl": round(self.open_pnl, 2),
            "realized_session": round(self.realized_session, 2),
            "daily_realized": round(self.daily_realized, 2),
            "peak_equity": round(self.peak_equity, 2),
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
            self._log("INFO", f"Seeded {len(self.closes)} public BTC marks for SMA warm-up.")
        except Exception as exc:
            self._log("WARN", f"History seed failed: {exc}")

    def _apply_execution(self, fill: ExecutionResult, actor: str) -> bool:
        side = fill.side
        qty = fill.qty
        price = fill.execution_price
        fee = fill.fee_usd

        if side == "buy":
            cost = price * qty + fee
            if cost > self.usd:
                self._log("WARN", "Insufficient paper USD for buy.")
                return False
            new_qty = self.btc + qty
            self.avg_entry = (
                (self.avg_entry * self.btc + price * qty) / new_qty if new_qty else 0.0
            )
            self.usd -= cost
            self.btc = new_qty
            self.state = "IN_POSITION"
        else:
            qty = min(qty, self.btc)
            if qty <= 0:
                return False
            # The request is normalized to available inventory before execution,
            # so fill.fee_usd is already based on this quantity.
            proceeds = price * qty - fee
            pnl = (price - self.avg_entry) * qty - fee
            self.usd += proceeds
            self.btc -= qty
            self.realized_session += pnl
            self.daily_realized += pnl
            if self.btc <= 1e-12:
                self.btc = 0.0
                self.avg_entry = 0.0
                self.state = "IDLE" if self.state != "OFFLINE" else "OFFLINE"

        self.peak_equity = max(self.peak_equity, self.equity)
        self._log(
            "FILL",
            (
                f"{actor} {side.upper()} {qty} BTC @ {price:.2f} "
                f"fee {fee:.2f} client_order_id={fill.client_order_id}"
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
            self.peak_equity = max(self.peak_equity, self.equity)
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
