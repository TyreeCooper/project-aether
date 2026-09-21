"""Paper engine with clean-bar strategy, cost-aware entries and managed exits."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx

from app import venue
from app.db import db_store
from app.persist import load_state, save_state
from app.risk import deny_entry
from app.strategy import (
    exit_plan,
    round_trip_cost_pct,
    sma,
    trend_breakout_snapshot,
    trend_exit_signal,
)

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
BAR_HISTORY = 1440
BREAKOUT_BARS = 6
EFFICIENCY_MIN = 0.35
COST_MULTIPLE = 1.4
COOLDOWN_MINUTES = 15
LOSS_STREAK_COOLDOWN_MINUTES = 30
TIME_STOP_MINUTES = 180


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def fee_inclusive_avg_entry(
    current_avg: float,
    current_qty: float,
    price: float,
    qty: float,
    fee: float,
) -> float:
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
        self.daily_realized_date = _now_dt().date().isoformat()
        self.peak_equity = STARTING_USD

        self.mark: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.mark_source = "kraken"
        self.watch_last: float | None = None
        self.watch_bid: float | None = None
        self.watch_ask: float | None = None
        self._last_watch_mono: float | None = None
        self.last_tick_age_ms = None
        self._last_tick_mono: float | None = None

        self.bars_1m = deque(maxlen=BAR_HISTORY)
        self.closes = deque(maxlen=BAR_HISTORY)
        self._forming_bar: dict[str, Any] | None = None
        self._forming_bucket: int | None = None

        self.audit = deque(maxlen=200)
        self.short_ma = SHORT_MA
        self.long_ma = LONG_MA
        self.stop_loss_pct = STOP_LOSS_PCT
        self.position_size = POSITION_BTC
        self.max_position = MAX_POSITION_BTC
        self.max_drawdown_pct = MAX_DRAWDOWN_PCT
        self.daily_loss_cap = DAILY_LOSS_CAP

        self.highest_since_entry = 0.0
        self.position_stop = 0.0
        self.entry_at: str | None = None
        self.last_exit_at: str | None = None
        self.cooldown_until: str | None = None
        self.consecutive_losses = 0
        self.last_strategy = {"regime": "warming", "reason": "warming", "signal": None}

        self._paper_entry_guard = lambda side="buy", protective=False: None
        self._task = None
        self._lock = asyncio.Lock()
        self._restore_file()
        self._log(
            "INFO",
            "Paper engine ready. Clean 1m bars, higher-timeframe filter, live execution blocked.",
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
        self.daily_realized_date = str(
            data.get("daily_realized_date") or self.daily_realized_date
        )
        self.peak_equity = float(data.get("peak_equity", self.peak_equity))
        if data.get("mark") is not None:
            self.mark = float(data["mark"])
        if data.get("bid") is not None:
            self.bid = float(data["bid"])
        if data.get("ask") is not None:
            self.ask = float(data["ask"])
        if data.get("mark_source"):
            self.mark_source = str(data["mark_source"])

        self.short_ma = int(data.get("short_ma", self.short_ma))
        self.long_ma = int(data.get("long_ma", self.long_ma))
        self.stop_loss_pct = float(data.get("stop_loss_pct", self.stop_loss_pct))
        self.position_size = float(data.get("position_size_btc", self.position_size))
        self.max_position = float(data.get("max_position_btc", self.max_position))
        self.max_drawdown_pct = float(data.get("max_drawdown_pct", self.max_drawdown_pct))
        self.daily_loss_cap = float(data.get("daily_loss_cap", self.daily_loss_cap))

        self.highest_since_entry = float(
            data.get("highest_since_entry", self.highest_since_entry) or 0
        )
        self.position_stop = float(data.get("position_stop", self.position_stop) or 0)
        self.entry_at = data.get("entry_at")
        self.last_exit_at = data.get("last_exit_at")
        self.cooldown_until = data.get("cooldown_until")
        self.consecutive_losses = int(
            data.get("consecutive_losses", self.consecutive_losses) or 0
        )

        restored_bars = data.get("bars_1m") or []
        if restored_bars:
            self.bars_1m.clear()
            self.closes.clear()
            for row in restored_bars[-BAR_HISTORY:]:
                if not isinstance(row, dict):
                    continue
                try:
                    clean = {
                        "ts": int(row["ts"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0) or 0),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
                self.bars_1m.append(clean)
                self.closes.append(clean["close"])
        elif data.get("closes"):
            self.closes.clear()
            for px in data.get("closes") or []:
                self.closes.append(float(px))

        self.audit.clear()
        for row in reversed(data.get("audit") or []):
            if isinstance(row, dict) and "message" in row:
                self.audit.appendleft(row)
        self._roll_daily_if_needed(persist=False)
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
            if self.btc > 0:
                self.state = "IN_POSITION"
                self.highest_since_entry = max(
                    self.highest_since_entry,
                    self.avg_entry,
                    float(self.mark or 0),
                )
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
            "daily_realized_date": self.daily_realized_date,
            "peak_equity": self.peak_equity,
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "mark_source": self.mark_source,
            "strategy": "sma_trend_breakout_v2",
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_btc": self.position_size,
            "max_position_btc": self.max_position,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_loss_cap": self.daily_loss_cap,
            "bars_1m": list(self.bars_1m)[-720:],
            "closes": list(self.closes)[-720:],
            "highest_since_entry": self.highest_since_entry,
            "position_stop": self.position_stop,
            "entry_at": self.entry_at,
            "last_exit_at": self.last_exit_at,
            "cooldown_until": self.cooldown_until,
            "consecutive_losses": self.consecutive_losses,
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

    def _roll_daily_if_needed(self, persist: bool = True) -> None:
        today = _now_dt().date().isoformat()
        if self.daily_realized_date == today:
            return
        prior = self.daily_realized
        self.daily_realized = 0.0
        self.daily_realized_date = today
        self._log("INFO", f"UTC daily P/L reset from {prior:.2f}.")
        if persist:
            self._persist()

    def _cooldown_active(self) -> bool:
        until = _parse_dt(self.cooldown_until)
        return bool(until and _now_dt() < until)

    def _strategy_snapshot(self) -> dict[str, Any]:
        try:
            return trend_breakout_snapshot(
                list(self.bars_1m),
                short_len=self.short_ma,
                long_len=self.long_ma,
                breakout_bars=BREAKOUT_BARS,
                efficiency_min=EFFICIENCY_MIN,
                cost_multiple=COST_MULTIPLE,
                mark=self.mark,
                bid=self.bid,
                ask=self.ask,
                fee_rate=TAKER_FEE,
            )
        except Exception as exc:
            return {"signal": None, "regime": "error", "reason": f"strategy_error:{exc}"}

    def snapshot(self) -> dict[str, Any]:
        age = None
        if self._last_tick_mono is not None:
            age = int((time.monotonic() - self._last_tick_mono) * 1000)
            self.last_tick_age_ms = age
        stale = age is None or age > STALE_MS
        self.last_strategy = self._strategy_snapshot()
        cost_pct = round_trip_cost_pct(
            self.mark,
            self.bid,
            self.ask,
            fee_rate=TAKER_FEE,
        )
        return {
            "state": self.state,
            "paper_mode": self.paper_mode,
            "live_blocked": self.live_blocked,
            "flatten_lock": self.flatten_lock,
            "strategy": "sma_trend_breakout_v2",
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_btc": self.position_size,
            "max_position_btc": self.max_position,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_loss_cap": self.daily_loss_cap,
            "bars": len(self.bars_1m),
            "warm_up_needed": max((self.long_ma + 2) * 15, 330),
            "short_value": sma(list(self.closes), self.short_ma),
            "long_value": sma(list(self.closes), self.long_ma),
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "mark_source": self.mark_source,
            "watch_last": self.watch_last,
            "last_tick_age_ms": age,
            "stale": stale,
            "usd": round(self.usd, 2),
            "btc": self.btc,
            "equity": round(self.equity, 2),
            "avg_entry": self.avg_entry,
            "open_pnl": round(self.open_pnl, 2),
            "realized_session": round(self.realized_session, 2),
            "daily_realized": round(self.daily_realized, 2),
            "daily_realized_date": self.daily_realized_date,
            "peak_equity": round(self.peak_equity, 2),
            "position_stop": round(self.position_stop, 2) if self.position_stop else None,
            "highest_since_entry": round(self.highest_since_entry, 2)
            if self.highest_since_entry
            else None,
            "cooldown_until": self.cooldown_until,
            "cooldown_active": self._cooldown_active(),
            "consecutive_losses": self.consecutive_losses,
            "round_trip_cost_pct": cost_pct,
            "regime": self.last_strategy.get("regime"),
            "strategy_reason": self.last_strategy.get("reason"),
            "strategy_metrics": self.last_strategy,
            "reason": "Paper machine. Clean 1m bars. Public Kraken tape. Live keys ignored.",
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

    async def _refresh_watch(self) -> None:
        if (
            self._last_watch_mono is not None
            and time.monotonic() - self._last_watch_mono < 30
        ):
            return
        self._last_watch_mono = time.monotonic()
        try:
            watch = await venue.fetch_binance_us()
            if watch:
                self.watch_last = float(watch["last"])
                self.watch_bid = float(watch["bid"])
                self.watch_ask = float(watch["ask"])
        except Exception as exc:
            self._log("WARN", f"Binance.US watch refresh failed: {exc}")

    async def seed_history(self) -> None:
        try:
            bars = await venue.fetch_bars(interval=1, limit=720)
            if len(bars) > 1:
                bars = bars[:-1]
            self.bars_1m.clear()
            self.closes.clear()
            for bar in bars[-720:]:
                clean = {
                    "ts": int(bar["ts"]),
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar.get("volume", 0) or 0),
                }
                self.bars_1m.append(clean)
                self.closes.append(clean["close"])
            if self.bars_1m:
                self.mark = float(self.bars_1m[-1]["close"])
                self.mark_source = "kraken"
            self._log(
                "INFO",
                f"Seeded {len(self.bars_1m)} completed Kraken 1m bars.",
            )
            self._persist()
        except Exception as exc:
            self._log("WARN", f"Kraken OHLC seed failed: {exc}")

    def _update_forming_bar(self, price: float) -> bool:
        """Return True when a completed 1m bar was appended."""
        now = _now_dt()
        bucket = int(now.timestamp() // 60) * 60
        if self._forming_bucket is None or self._forming_bar is None:
            self._forming_bucket = bucket
            self._forming_bar = {
                "ts": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            }
            return False
        if bucket == self._forming_bucket:
            self._forming_bar["high"] = max(float(self._forming_bar["high"]), price)
            self._forming_bar["low"] = min(float(self._forming_bar["low"]), price)
            self._forming_bar["close"] = price
            return False

        completed = dict(self._forming_bar)
        self.bars_1m.append(completed)
        self.closes.append(float(completed["close"]))
        self._forming_bucket = bucket
        self._forming_bar = {
            "ts": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0.0,
        }
        return True

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

    def _initialize_position_controls(self) -> None:
        if self.btc <= 0 or self.avg_entry <= 0 or not self.mark:
            return
        self.highest_since_entry = max(
            self.highest_since_entry,
            self.avg_entry,
            float(self.mark),
        )
        if not self.entry_at:
            self.entry_at = _now()
        cost = round_trip_cost_pct(self.mark, self.bid, self.ask, TAKER_FEE)
        plan = exit_plan(
            list(self.bars_1m),
            self.avg_entry,
            self.highest_since_entry,
            float(self.mark),
            self.stop_loss_pct,
            cost,
        )
        self.position_stop = max(self.position_stop, float(plan["active_stop"]))

    def _register_flat_exit(self, realized_pnl: float) -> None:
        self.last_exit_at = _now()
        if realized_pnl < -1e-9:
            self.consecutive_losses += 1
        elif realized_pnl > 1e-9:
            self.consecutive_losses = 0
        minutes = (
            LOSS_STREAK_COOLDOWN_MINUTES
            if self.consecutive_losses >= 2
            else COOLDOWN_MINUTES
        )
        self.cooldown_until = (_now_dt() + timedelta(minutes=minutes)).isoformat()
        self.highest_since_entry = 0.0
        self.position_stop = 0.0
        self.entry_at = None
        self._log(
            "RISK",
            f"Entry cooldown set for {minutes} minutes after exit.",
            {
                "kind": "risk",
                "reason": "post_exit_cooldown",
                "cooldown_minutes": minutes,
                "consecutive_losses": self.consecutive_losses,
            },
        )

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
            self._initialize_position_controls()
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
                self.state = "IDLE" if self.state != "OFFLINE" else "OFFLINE"
                self._register_flat_exit(realized_pnl)

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

    def _manage_open_position(self, new_bar: bool) -> bool:
        if self.btc <= 0 or self.avg_entry <= 0 or not self.mark:
            return False
        self.highest_since_entry = max(self.highest_since_entry, float(self.mark))
        cost = round_trip_cost_pct(self.mark, self.bid, self.ask, TAKER_FEE)
        plan = exit_plan(
            list(self.bars_1m),
            self.avg_entry,
            self.highest_since_entry,
            float(self.mark),
            self.stop_loss_pct,
            cost,
        )
        self.position_stop = max(self.position_stop, float(plan["active_stop"]))

        reason = None
        if self.position_stop and self.mark <= self.position_stop:
            reason = "managed_stop"
        elif new_bar and trend_exit_signal(
            list(self.bars_1m),
            self.short_ma,
            self.long_ma,
        ):
            reason = "trend_failure"
        else:
            entered = _parse_dt(self.entry_at)
            if entered:
                age_minutes = (_now_dt() - entered).total_seconds() / 60
                gain_pct = ((self.mark / self.avg_entry) - 1) * 100
                if (
                    age_minutes >= TIME_STOP_MINUTES
                    and gain_pct < cost * 1.25
                ):
                    reason = "time_stop"

        if not reason:
            return False
        px = self._fill_price("sell")
        if not px:
            return False
        self._log(
            "BOT",
            f"Managed exit: {reason} at {self.mark:.2f}; stop {self.position_stop:.2f}.",
        )
        return self._apply_fill("sell", self.btc, px, f"bot-{reason}")

    def evaluate_and_maybe_trade(self, new_bar: bool = False) -> None:
        if self.state not in ("IDLE", "IN_POSITION") or not self.mark:
            return
        self._roll_daily_if_needed()
        if self._manage_open_position(new_bar):
            return
        if self.btc > 0 or not new_bar:
            return
        if self._cooldown_active():
            return

        self.last_strategy = self._strategy_snapshot()
        if self.last_strategy.get("signal") != "buy":
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
            max_drawdown_pct=self.max_drawdown_pct,
            daily_realized=self.daily_realized,
            daily_loss_cap=self.daily_loss_cap,
        )
        if not reason:
            reason = self._paper_entry_guard(side="buy", protective=False)
        if reason:
            self._risk_denied(reason, self.position_size, "bot")
            return

        px = self._fill_price("buy")
        self._log(
            "BOT",
            (
                "Qualified SMA trend breakout. "
                f"eff={self.last_strategy.get('efficiency')} "
                f"edge={self.last_strategy.get('opportunity_pct')}% "
                f"cost={self.last_strategy.get('cost_pct')}%."
            ),
        )
        if px:
            self._apply_fill("buy", self.position_size, px, "bot")

    async def tick(self) -> None:
        tick = await self.fetch_mark()
        if tick is None:
            return
        await self._refresh_watch()
        async with self._lock:
            self.mark = float(tick["last"])
            self.bid = float(tick["bid"]) if tick.get("bid") is not None else None
            self.ask = float(tick["ask"]) if tick.get("ask") is not None else None
            self.mark_source = tick.get("source", self.mark_source)
            self._last_tick_mono = time.monotonic()
            self._roll_daily_if_needed()
            new_bar = self._update_forming_bar(self.mark)
            self.peak_equity = max(self.peak_equity, self.equity)
            self.evaluate_and_maybe_trade(new_bar=new_bar)
            if new_bar:
                self._persist()

    async def loop(self) -> None:
        await self.seed_history()
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self._log("ERROR", f"Tick fault: {exc}")
            await asyncio.sleep(POLL_SECONDS)

    def start_loop(self) -> None:
        if self._task is None or getattr(self._task, "done", lambda: True)():
            self._task = asyncio.create_task(self.loop())

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await db_store.flush()

    async def update_config(self, config: dict[str, Any]):
        async with self._lock:
            if self.state != "OFFLINE" or self.btc > 0:
                return {"ok": False, "error": "config_requires_offline_flat"}

            short_ma = int(config.get("short_ma", self.short_ma))
            long_ma = int(config.get("long_ma", self.long_ma))
            stop_loss_pct = float(config.get("stop_loss_pct", self.stop_loss_pct))
            position_size = float(config.get("position_size_btc", self.position_size))
            max_position = float(config.get("max_position_btc", self.max_position))
            max_drawdown_pct = float(
                config.get("max_drawdown_pct", self.max_drawdown_pct)
            )
            daily_loss_cap = float(
                config.get("daily_loss_cap", self.daily_loss_cap)
            )

            if not 2 <= short_ma <= 100:
                return {"ok": False, "error": "short_ma_out_of_range"}
            if not short_ma < long_ma <= 200:
                return {"ok": False, "error": "long_ma_must_exceed_short_ma"}
            if not 0.1 <= stop_loss_pct <= 20:
                return {"ok": False, "error": "stop_loss_pct_out_of_range"}
            if not 0 < position_size <= max_position:
                return {"ok": False, "error": "position_size_exceeds_max"}
            if not 0 < max_position <= 1:
                return {"ok": False, "error": "max_position_out_of_range"}
            if not 0.5 <= max_drawdown_pct <= 50:
                return {"ok": False, "error": "max_drawdown_pct_out_of_range"}
            if not 1 <= daily_loss_cap <= 10000:
                return {"ok": False, "error": "daily_loss_cap_out_of_range"}

            self.short_ma = short_ma
            self.long_ma = long_ma
            self.stop_loss_pct = stop_loss_pct
            self.position_size = position_size
            self.max_position = max_position
            self.max_drawdown_pct = max_drawdown_pct
            self.daily_loss_cap = daily_loss_cap
            self._log(
                "CONFIG",
                "Operator updated paper strategy/risk configuration.",
                {
                    "kind": "config",
                    "short_ma": short_ma,
                    "long_ma": long_ma,
                    "stop_loss_pct": stop_loss_pct,
                    "position_size_btc": position_size,
                    "max_position_btc": max_position,
                    "max_drawdown_pct": max_drawdown_pct,
                    "daily_loss_cap": daily_loss_cap,
                },
            )
            self._persist()
            return {"ok": True, **self.snapshot()}

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
                    max_drawdown_pct=self.max_drawdown_pct,
                    daily_realized=self.daily_realized,
                    daily_loss_cap=self.daily_loss_cap,
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
            self._log("INFO", "Emergency flatten complete. Entries locked.")
            self._persist()
            return {"ok": True, **self.snapshot()}

    async def unlock(self):
        async with self._lock:
            self.flatten_lock = False
            self._log("INFO", "Flatten lock cleared by operator.")
            self._persist()
            return {"ok": True, **self.snapshot()}


engine = PaperEngine()
