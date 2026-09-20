"""Paper engine with PostgreSQL-first persistence and public Kraken tape."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app import venue
from app.db import db_store
from app.persist import load_state, save_state
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
STALE_MS = 15_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fee_inclusive_avg_entry(
    current_avg: float,
    current_qty: float,
    price: float,
    qty: float,
    fee: float,
) -> float:
    """Weighted BTC cost basis including buy-side fees."""
    new_qty = current_qty + qty
    if new_qty <= 0:
        return 0.0
    prior_cost = current_avg * current_qty
    new_cost = price * qty + fee
    return (prior_cost + new_cost) / new_qty


class PaperEngine:
    def __init__(self) -> None:
        self.paper_mode = True
        self.live_blocked = True
        self.state = "OFFLINE"
        self.flatten_lock = False
        self.usd = STARTING_USD
        self.btc = 0.0
        self.avg_entry = 0.0
        self.realized_session = 0.0
        self.daily_realized = 0.0
        self.peak_equity = STARTING_USD
        self.mark = None
        self.bid = None
        self.ask = None
        self.mark_source = "kraken"
        self.last_tick_age_ms = None
        self._last_tick_mono = None
        self.closes = deque(maxlen=300)
        self.audit = deque(maxlen=200)
        self.short_ma = SHORT_MA
        self.long_ma = LONG_MA
        self.stop_loss_pct = STOP_LOSS_PCT
        self.position_size = POSITION_BTC
        self.max_position = MAX_POSITION_BTC
        self._task = None
        self._lock = asyncio.Lock()
        self._restore_file()
        self._log(
            "INFO",
            "Paper engine ready. Venue tape is public Kraken. Live execution blocked.",
        )

    def _apply_state(self, data: dict[str, Any], source: str) -> None:
        self.state = data.get("state", self.state)
        if self.state not in ("OFFLINE", "IDLE", "IN_POSITION"):
            self.state = "OFFLINE"
        self.flatten_lock = bool(data.get("flatten_lock", False))
        self.usd = float(data.get("usd", self.usd))
        self.btc = float(data.get("btc", self.btc))
        self.avg_entry = float(data.get("avg_entry", 0.0))
        self.realized_session = float(data.get("realized_session", 0.0))
        self.daily_realized = float(data.get("daily_realized", 0.0))
        self.peak_equity = float(data.get("peak_equity", self.peak_equity))
        if data.get("mark") is not None:
            self.mark = float(data["mark"])
        if data.get("bid") is not None:
            self.bid = float(data["bid"])
        if data.get("ask") is not None:
            self.ask = float(data["ask"])
        if data.get("mark_source"):
            self.mark_source = str(data["mark_source"])

        self.closes.clear()
        for px in data.get("closes") or []:
            self.closes.append(float(px))

        self.audit.clear()
        for row in reversed(data.get("audit") or []):
            if isinstance(row, dict) and "message" in row:
                self.audit.appendleft(row)
        self._log("INFO", f"Restored paper ledger from {source}.")

    def _restore_file(self) -> None:
        data = load_state()
        if data:
            self._apply_state(data, "disk fallback")

    async def initialize_persistence(self) -> None:
        await db_store.initialize()
        if not db_store.initialized:
            return
        db_state = await db_store.load_state()
        if db_state:
            self._apply_state(db_state, "PostgreSQL")
            # Fail-safe restart policy:
            # - Flat accounts never auto-rearm after a process/App Service restart.
            # - Existing positions remain IN_POSITION so protective exits can still run.
            if self.btc > 0:
                self.state = "IN_POSITION"
                self._log(
                    "SAFETY",
                    "Restart recovery detected an open position; protective management remains active.",
                )
            else:
                self.state = "OFFLINE"
                self._log(
                    "SAFETY",
                    "Restart recovery forced bot OFFLINE; operator re-arm required.",
                )
            self._persist()
        else:
            self.state = "OFFLINE"
            await db_store.save_state(self._state_payload())

    def _state_payload(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "state": self.state,
            "flatten_lock": self.flatten_lock,
            "usd": self.usd,
            "btc": self.btc,
            "equity": self.equity,
            "avg_entry": self.avg_entry,
            "open_pnl": self.open_pnl,
            "realized_session": self.realized_session,
            "daily_realized": self.daily_realized,
            "peak_equity": self.peak_equity,
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "mark_source": self.mark_source,
            "strategy": "sma_crossover",
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_btc": self.position_size,
            "max_position_btc": self.max_position,
            "closes": list(self.closes)[-80:],
            "audit": list(self.audit)[:50],
            "saved_at": _now(),
            "stale": snap.get("stale"),
        }

    def _persist(self) -> None:
        payload = self._state_payload()
        save_state(payload)
        db_store.schedule_save(payload)

    def _log(
        self,
        level: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "event_id": uuid4().hex,
            "ts": _now(),
            "level": level,
            "message": message,
        }
        if data is not None:
            row["data"] = data
        self.audit.appendleft(row)

    def _fill_price(self, side: str) -> float | None:
        if side == "buy":
            return self.ask or self.mark
        return self.bid or self.mark

    @property
    def equity(self) -> float:
        return self.usd + self.btc * (self.mark or 0.0)

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
        stale = age is None or age > STALE_MS
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
            "max_position_btc": self.max_position,
            "bars": len(self.closes),
            "warm_up_needed": self.long_ma + 1,
            "short_value": sma(list(self.closes), self.short_ma),
            "long_value": sma(list(self.closes), self.long_ma),
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "mark_source": self.mark_source,
            "last_tick_age_ms": age,
            "stale": stale,
            "usd": round(self.usd, 2),
            "btc": self.btc,
            "equity": round(self.equity, 2),
            "avg_entry": self.avg_entry,
            "open_pnl": round(self.open_pnl, 2),
            "realized_session": round(self.realized_session, 2),
            "daily_realized": round(self.daily_realized, 2),
            "peak_equity": round(self.peak_equity, 2),
            "reason": "Paper machine. Public Kraken tape. Live keys ignored.",
        }

    async def fetch_mark(self):
        try:
            tick = await venue.fetch_ticker()
            if tick:
                return tick
        except Exception as exc:
            self._log("WARN", f"Kraken ticker failed: {exc}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                res.raise_for_status()
                last = float(res.json()["bitcoin"]["usd"])
                return {
                    "last": last,
                    "bid": last,
                    "ask": last,
                    "source": "coingecko",
                }
        except Exception as exc:
            self._log("WARN", f"Mark fetch failed: {exc}")
            return None

    async def seed_history(self) -> None:
        if len(self.closes) >= self.long_ma + 1:
            return
        try:
            closes = await venue.fetch_closes()
            for px in closes:
                self.closes.append(px)
            if self.closes:
                self.mark = self.closes[-1]
                self._last_tick_mono = time.monotonic()
                self.mark_source = "kraken"
            self._log(
                "INFO",
                f"Seeded {len(self.closes)} Kraken 1m closes for SMA warm-up.",
            )
            self._persist()
            return
        except Exception as exc:
            self._log("WARN", f"Kraken OHLC failed: {exc}")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(
                    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                    params={"vs_currency": "usd", "days": "1"},
                )
                res.raise_for_status()
                prices = res.json().get("prices") or []
            for _ts, px in prices[-120:]:
                self.closes.append(float(px))
            if self.closes:
                self.mark = self.closes[-1]
                self._last_tick_mono = time.monotonic()
                self.mark_source = "coingecko"
            self._log(
                "INFO",
                f"Seeded {len(self.closes)} CoinGecko marks (fallback).",
            )
            self._persist()
        except Exception as exc:
            self._log("WARN", f"History seed failed: {exc}")

    def _risk_denied(self, reason: str, qty: float, actor: str) -> None:
        self._log(
            "WARN",
            f"Buy denied: {reason}",
            {
                "kind": "risk",
                "reason": reason,
                "actor": actor,
                "requested_qty_btc": qty,
                "current_position_btc": self.btc,
                "max_position_btc": self.max_position,
                "equity": self.equity,
                "daily_realized": self.daily_realized,
            },
        )
        self._persist()

    def _apply_fill(
        self,
        side: str,
        qty: float,
        price: float,
        actor: str,
    ) -> bool:
        requested_qty = qty
        if side == "sell":
            qty = min(qty, self.btc)
            if qty <= 0:
                return False

        fee = price * qty * TAKER_FEE
        if side == "buy":
            cost = price * qty + fee
            if cost > self.usd:
                self._risk_denied("insufficient_paper_usd", qty, actor)
                return False

        execution_id = uuid4().hex
        self._log(
            "ORDER",
            f"{actor} {side.upper()} request {requested_qty} BTC",
            {
                "kind": "order",
                "execution_id": execution_id,
                "actor": actor,
                "side": side,
                "requested_qty_btc": requested_qty,
                "status": "accepted",
            },
        )

        realized_pnl = 0.0
        if side == "buy":
            new_qty = self.btc + qty
            self.avg_entry = fee_inclusive_avg_entry(
                self.avg_entry,
                self.btc,
                price,
                qty,
                fee,
            )
            self.usd -= price * qty + fee
            self.btc = new_qty
            self.state = "IN_POSITION"
        else:
            proceeds = price * qty - fee
            realized_pnl = (price - self.avg_entry) * qty - fee
            self.usd += proceeds
            self.btc -= qty
            self.realized_session += realized_pnl
            self.daily_realized += realized_pnl
            if self.btc <= 1e-12:
                self.btc = 0.0
                self.avg_entry = 0.0
                self.state = (
                    "IDLE" if self.state != "OFFLINE" else "OFFLINE"
                )

        self.peak_equity = max(self.peak_equity, self.equity)
        self._log(
            "FILL",
            (
                f"{actor} {side.upper()} {qty} BTC @ {price:.2f} "
                f"fee {fee:.2f} src {self.mark_source}"
            ),
            {
                "kind": "fill",
                "execution_id": execution_id,
                "actor": actor,
                "side": side,
                "qty_btc": qty,
                "price_usd": price,
                "fee_usd": fee,
                "realized_pnl_usd": realized_pnl,
                "mark_source": self.mark_source,
            },
        )
        self._persist()
        return True

    def evaluate_and_maybe_trade(self) -> None:
        if self.state not in ("IDLE", "IN_POSITION") or not self.mark:
            return
        if self.btc > 0 and self.avg_entry > 0:
            stop = self.avg_entry * (1 - self.stop_loss_pct / 100)
            if self.mark <= stop:
                px = self._fill_price("sell")
                self._log(
                    "BOT",
                    f"Stop-loss hit at {self.mark:.2f} (stop {stop:.2f}).",
                )
                if px:
                    self._apply_fill("sell", self.btc, px, "bot-stop")
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
                self._risk_denied(reason, self.position_size, "bot")
                return
            px = self._fill_price("buy")
            self._log(
                "BOT",
                f"SMA cross-up. Paper BUY {self.position_size} BTC",
            )
            if px:
                self._apply_fill("buy", self.position_size, px, "bot")
        elif signal == "sell" and self.btc > 0:
            px = self._fill_price("sell")
            self._log("BOT", "SMA cross-down. Paper SELL inventory")
            if px:
                self._apply_fill("sell", self.btc, px, "bot")

    async def tick(self) -> None:
        tick = await self.fetch_mark()
        if tick is None:
            return
        async with self._lock:
            self.mark = tick["last"]
            self.bid = tick.get("bid")
            self.ask = tick.get("ask")
            self.mark_source = tick.get("source", self.mark_source)
            self.closes.append(self.mark)
            self._last_tick_mono = time.monotonic()
            self.peak_equity = max(self.peak_equity, self.equity)
            self.evaluate_and_maybe_trade()

    async def loop(self) -> None:
        await self.seed_history()
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self._log("ERROR", f"Tick fault: {exc}")
            await asyncio.sleep(POLL_SECONDS)

    def start_loop(self) -> None:
        if self._task is None or getattr(
            self._task, "done", lambda: True
        )():
            self._task = asyncio.create_task(self.loop())

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await db_store.flush()

    async def start_bot(self):
        async with self._lock:
            if self.flatten_lock:
                return {"ok": False, "error": "flatten_lock"}
            self.state = "IN_POSITION" if self.btc > 0 else "IDLE"
            self._log("INFO", f"Bot armed ({self.state}).")
            self._persist()
            return {"ok": True, **self.snapshot()}

    async def stop_bot(self):
        async with self._lock:
            self.state = "OFFLINE"
            self._log("INFO", "Bot disarmed. Position left untouched.")
            self._persist()
            return {"ok": True, **self.snapshot()}

    async def manual(self, side: str, qty=None):
        async with self._lock:
            px = self._fill_price(side)
            if not px:
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
                    self._risk_denied(reason, qty, "operator")
                    return {
                        "ok": False,
                        "error": reason,
                        "requested_qty_btc": qty,
                        "current_position_btc": self.btc,
                        "max_position_btc": self.max_position,
                    }
            filled = self._apply_fill(side, qty, px, "operator")
            if not filled:
                return {"ok": False, "error": "order_not_filled"}
            return {"ok": True, **self.snapshot()}

    async def flatten(self):
        async with self._lock:
            self.flatten_lock = True
            px = self._fill_price("sell")
            if self.btc > 0 and px:
                self._apply_fill("sell", self.btc, px, "flatten")
            self.state = "OFFLINE"
            self._log(
                "INFO",
                "Emergency flatten complete. Entries locked.",
            )
            self._persist()
            return {"ok": True, **self.snapshot()}

    async def unlock(self):
        async with self._lock:
            self.flatten_lock = False
            self._log("INFO", "Flatten lock cleared by operator.")
            self._persist()
            return {"ok": True, **self.snapshot()}


engine = PaperEngine()
