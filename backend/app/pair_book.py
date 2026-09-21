"""One Kraken pair book. Own bars and position, shared wallet."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.clock import is_new_five_minute
from app.exits import stop_fill_price, time_stop_due
from app.fees import TAKER_FEE
from app.lots import size_ok, volume_min
from app.paper_exec import SLIPPAGE_BPS, slipped_price
from app.strategy import exit_plan, trend_breakout_snapshot

BAR_HISTORY = 720


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PairBook:
    def __init__(self, asset: dict[str, Any], wallet) -> None:
        self.id = str(asset["id"])
        self.symbol = str(asset["symbol"])
        self.pair = str(asset["pair"])
        self.kraken = str(asset["kraken"])
        self.tv = str(asset.get("tv") or "")
        self.wallet = wallet
        self.bars: deque[dict[str, Any]] = deque(maxlen=BAR_HISTORY)
        self.last_5m: int | None = None
        self.mark: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.watch_last: float | None = None
        self.stop = 0.0
        self.highest = 0.0
        self.entry_at: str | None = None
        self.fills: list[dict[str, Any]] = []
        self.last_reason = "warming"
        self.signal: str | None = None

    def apply_quote(self, item: dict[str, Any]) -> None:
        if item.get("last") is not None:
            self.mark = float(item["last"])
        if item.get("bid") is not None:
            self.bid = float(item["bid"])
        if item.get("ask") is not None:
            self.ask = float(item["ask"])
        if item.get("watch_last") is not None:
            self.watch_last = float(item["watch_last"])

    def seed(self, bars: list[dict[str, Any]]) -> None:
        self.bars.clear()
        for bar in bars[-BAR_HISTORY:]:
            self.bars.append(bar)
        if self.bars:
            self.mark = float(self.bars[-1]["close"])
            _, self.last_5m = is_new_five_minute(list(self.bars), None)

    def qty(self) -> float:
        return self.wallet.qty(self.id)

    def snapshot_strategy(self) -> dict[str, Any]:
        snap = trend_breakout_snapshot(
            list(self.bars),
            mark=self.mark,
            bid=self.bid,
            ask=self.ask,
            fee_rate=TAKER_FEE,
        )
        self.signal = snap.get("signal")
        self.last_reason = str(snap.get("reason") or "")
        return snap

    def wants_entry(self) -> bool:
        if self.qty() > 0:
            return False
        snap = self.snapshot_strategy()
        return snap.get("signal") == "buy"

    def fill_px(self, side: str) -> float | None:
        return slipped_price(side, self.bid, self.ask, self.mark)

    def enter(self, risk_usd: float) -> dict[str, Any]:
        px = self.fill_px("buy")
        if not px:
            return {"ok": False, "error": "no_mark", "pair": self.pair}
        qty = risk_usd / px
        ok, why = size_ok(self.id, qty, px)
        if not ok:
            qty = max(volume_min(self.id), (0.5 + 0.01) / px)
            ok, why = size_ok(self.id, qty, px)
            if not ok:
                return {"ok": False, "error": why, "pair": self.pair}
        result = self.wallet.buy(self.id, qty, px)
        result["pair"] = self.pair
        result["actor"] = "bot-v3-entry"
        if result.get("ok"):
            self.entry_at = _now()
            self.highest = px
            self.stop = px * 0.98
            self.fills.append({**result, "side": "buy", "ts": self.entry_at})
        return result

    def manage(self) -> dict[str, Any] | None:
        qty = self.qty()
        if qty <= 0 or not self.mark:
            return None
        self.highest = max(self.highest, float(self.mark))
        plan = exit_plan(
            list(self.bars),
            self.wallet.avg_entry(self.id),
            self.highest,
            self.mark,
            2.0,
            TAKER_FEE * 200,
            frozen_hard_stop=self.stop,
        )
        stop = float(plan.get("hard_stop") or self.stop or 0)
        if stop:
            self.stop = max(self.stop, stop)
        low = float(self.bars[-1]["low"]) if self.bars else self.mark
        hit = self.stop > 0 and low <= self.stop
        held = None
        if self.entry_at:
            try:
                entered = datetime.fromisoformat(self.entry_at.replace("Z", "+00:00"))
                held = int((datetime.now(timezone.utc) - entered).total_seconds() // 60)
            except ValueError:
                held = None
        avg = self.wallet.avg_entry(self.id) or self.mark
        gain = ((self.mark / avg) - 1) * 100
        timed = time_stop_due(held, gain, TAKER_FEE * 200)
        weak = bool(plan.get("exit"))
        if not (hit or timed or weak):
            return None
        raw = stop_fill_price(self.stop) if hit and self.stop else self.fill_px("sell")
        if not raw:
            return None
        result = self.wallet.sell(self.id, qty, raw)
        result["pair"] = self.pair
        result["actor"] = "bot-v3-managed_stop" if hit else "bot-v3-time_stop" if timed else "bot-v3-exit"
        if result.get("ok"):
            self.entry_at = None
            self.stop = 0.0
            self.fills.append({**result, "side": "sell", "ts": _now()})
        return result

    def view(self) -> dict[str, Any]:
        qty = self.qty()
        avg = self.wallet.avg_entry(self.id)
        return {
            "id": self.id,
            "symbol": self.symbol,
            "pair": self.pair,
            "kraken": self.kraken,
            "tv": self.tv,
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "watch_last": self.watch_last,
            "qty": qty,
            "avg": avg,
            "stop": self.stop or None,
            "open_pnl": (self.mark - avg) * qty if qty and self.mark else 0.0,
            "bars": len(self.bars),
            "signal": self.signal,
            "reason": self.last_reason,
            "paper": True,
        }
