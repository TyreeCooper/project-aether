"""One Aether asset book. Own bars and strategy state, shared paper portfolio."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.clock import is_new_five_minute
from app.exits import stop_fill_price, time_stop_due
from app.fees import fee_rate
from app.paper_exec import slipped_price
from app.playbooks import playbook_profile, playbook_snapshot
from app.sessions import for_asset
from app.strategy import exit_plan, resample_bars

BAR_HISTORY = 720


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PairBook:
    def __init__(self, asset: dict[str, Any], wallet) -> None:
        self.id = str(asset["id"])
        self.name = str(asset.get("name") or asset["symbol"])
        self.symbol = str(asset["symbol"])
        self.pair = str(asset["pair"])
        self.kraken = str(asset.get("kraken") or "")
        self.tv = str(asset.get("tv") or "")
        self.broker = str(asset.get("broker") or asset.get("venue") or "")
        self.style = str(asset.get("style") or "")
        self.wallet = wallet
        self.bars: deque[dict[str, Any]] = deque(maxlen=BAR_HISTORY)
        self.bars_1h: deque[dict[str, Any]] = deque(maxlen=720)
        self.bars_1d: deque[dict[str, Any]] = deque(maxlen=400)
        self.last_5m: int | None = None
        self.mark: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.watch_last: float | None = None
        self.open_24h: float | None = None
        self.high_24h: float | None = None
        self.low_24h: float | None = None
        self.volume_24h: float | None = None
        self.vwap_24h: float | None = None
        self.trades_24h: int | None = None
        self.stop = 0.0
        self.highest = 0.0
        self.lowest = 0.0
        self.entry_at: str | None = None
        self.entry_mode: str | None = None
        self.last_entry_signal_key: str | None = None
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
        for attr in ("open_24h", "high_24h", "low_24h", "volume_24h", "vwap_24h"):
            if item.get(attr) is not None:
                setattr(self, attr, float(item[attr]))
        if item.get("trades_24h") is not None:
            self.trades_24h = int(item["trades_24h"])

    def push_px(self, ts: int) -> None:
        if not self.mark:
            return
        bucket = int(ts) // 60 * 60
        px = float(self.mark)
        if self.bars and int(self.bars[-1]["ts"]) == bucket:
            row = self.bars[-1]
            row["high"] = max(float(row["high"]), px)
            row["low"] = min(float(row["low"]), px)
            row["close"] = px
            return
        self.bars.append(
            {"ts": bucket, "open": px, "high": px, "low": px, "close": px, "volume": 0.0}
        )

    def seed(self, bars: list[dict[str, Any]]) -> None:
        self.bars.clear()
        for bar in bars[-BAR_HISTORY:]:
            self.bars.append(bar)
        if self.bars:
            self.mark = float(self.bars[-1]["close"])
            _, self.last_5m = is_new_five_minute(list(self.bars), None)

    def seed_context(self, bars_1h: list[dict[str, Any]]) -> None:
        self.bars_1h.clear()
        for bar in bars_1h[-720:]:
            self.bars_1h.append(bar)

    def seed_daily(self, bars_1d: list[dict[str, Any]]) -> None:
        self.bars_1d.clear()
        for bar in bars_1d[-400:]:
            self.bars_1d.append(bar)

    def qty(self) -> float:
        return self.wallet.qty(self.id)

    def position_side(self) -> str | None:
        side = getattr(self.wallet, "side", None)
        return side(self.id) if callable(side) else ("long" if self.qty() > 0 else None)

    def snapshot_strategy(
        self,
        *,
        btc_bias_on: bool = False,
        btc_in_position: bool = False,
    ) -> dict[str, Any]:
        clock = for_asset(self.id)
        active_ids = {
            str(row.get("id"))
            for row in clock.get("sessions") or []
            if row.get("active")
        }
        rate = fee_rate(
            self.id,
            qty=max(self.qty(), 1.0),
            price=float(self.mark or 1.0),
            side="buy",
        )
        snap = playbook_snapshot(
            self.id,
            list(self.bars),
            list(self.bars_1h),
            list(self.bars_1d),
            mark=self.mark,
            bid=self.bid,
            ask=self.ask,
            fee_rate=rate,
            active_session_ids=active_ids,
            in_position=self.qty() > 0,
            btc_bias_on=btc_bias_on,
            btc_in_position=btc_in_position,
            position_side=self.position_side(),
        )
        if (
            snap.get("executable_signal") in {"buy", "short"}
            and snap.get("signal_key")
            and str(snap.get("signal_key")) == str(self.last_entry_signal_key)
        ):
            snap["executable_signal"] = None
            snap["execution_status"] = "signal_already_consumed"
        self.signal = snap.get("signal")
        self.last_reason = str(snap.get("reason") or "")
        return snap

    def wants_entry(
        self,
        *,
        btc_bias_on: bool = False,
        btc_in_position: bool = False,
    ) -> bool:
        if self.qty() > 0:
            return False
        snap = self.snapshot_strategy(
            btc_bias_on=btc_bias_on,
            btc_in_position=btc_in_position,
        )
        return snap.get("executable_signal") in {"buy", "short"}

    def fill_px(self, side: str) -> float | None:
        return slipped_price(side, self.bid, self.ask, self.mark)

    def enter(
        self,
        risk_usd: float,
        *,
        strategy_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snap = dict(strategy_snapshot or {})
        executable = str(snap.get("executable_signal") or "").lower()
        if executable not in {"buy", "short"}:
            return {
                "ok": False,
                "error": "no_executable_signal",
                "pair": self.pair,
            }
        position_side = "short" if executable == "short" else "long"
        fill_side = "sell" if position_side == "short" else "buy"
        reference = (
            self.bid
            if position_side == "short" and self.bid is not None
            else self.ask
            if position_side == "long" and self.ask is not None
            else self.mark
        )
        px = self.fill_px(fill_side)
        if not px:
            return {"ok": False, "error": "no_mark", "pair": self.pair}

        stop_pct = max(float(snap.get("risk_stop_pct") or 2.0), 0.01)
        stop_price = (
            px * (1 + stop_pct / 100)
            if position_side == "short"
            else px * (1 - stop_pct / 100)
        )
        size_for_risk = getattr(self.wallet, "size_for_risk", None)
        if not callable(size_for_risk):
            return {
                "ok": False,
                "error": "paper_portfolio_required",
                "pair": self.pair,
            }
        qty = float(
            size_for_risk(
                self.id,
                side=position_side,
                risk_usd=float(risk_usd),
                entry_price=px,
                stop_price=stop_price,
            )
            or 0.0
        )
        if qty <= 0:
            return {
                "ok": False,
                "error": "risk_size_below_minimum",
                "pair": self.pair,
            }

        open_position = getattr(self.wallet, "open_position", None)
        if not callable(open_position):
            return {
                "ok": False,
                "error": "paper_portfolio_required",
                "pair": self.pair,
            }
        result = open_position(
            self.id,
            side=position_side,
            quantity=qty,
            price=px,
            stop_price=stop_price,
            mode=str(snap.get("mode") or "intraday"),
            signal_key=(
                str(snap.get("signal_key"))
                if snap.get("signal_key") is not None
                else None
            ),
            reference_price=float(reference or px),
        )
        result["pair"] = self.pair
        result["actor"] = "bot-playbook-entry"
        result["position_side"] = position_side
        result["execution_side"] = fill_side
        result["event"] = "entry"
        if result.get("ok"):
            self.entry_at = str(result.get("opened_at") or _now())
            self.entry_mode = str(snap.get("mode") or "intraday")
            self.highest = px
            self.lowest = px
            self.stop = stop_price
            result["entry_mode"] = self.entry_mode
            result["risk_stop_pct"] = stop_pct
            signal_key = snap.get("signal_key")
            if signal_key:
                self.last_entry_signal_key = str(signal_key)
                result["signal_key"] = self.last_entry_signal_key
            reference_px = float(reference or px)
            move_pnl = getattr(self.wallet, "move_pnl", None)
            if callable(move_pnl):
                adverse = float(
                    move_pnl(
                        self.id,
                        side=position_side,
                        quantity=qty,
                        entry_price=reference_px,
                        mark=px,
                    )
                )
                slippage_usd = max(-adverse, 0.0)
            else:
                slippage_usd = 0.0
            slippage_bps = (
                abs(px / reference_px - 1) * 10_000
                if reference_px > 0
                else None
            )
            result["reference_price"] = reference_px
            result["slippage_usd"] = round(slippage_usd, 8)
            result["slippage_bps"] = (
                None if slippage_bps is None else round(slippage_bps, 4)
            )
            self.fills.append(
                {
                    **result,
                    "side": fill_side,
                    "ts": self.entry_at,
                }
            )
        return result

    def current_excursion(self, entry_price: float | None = None) -> dict[str, Any]:
        entry = float(entry_price or self.wallet.avg_entry(self.id) or 0.0)
        if entry <= 0 or not self.entry_at:
            return {"mfe_pct": None, "mae_pct": None, "available_move_pct": None}
        try:
            entered = datetime.fromisoformat(self.entry_at.replace("Z", "+00:00"))
            entered_ts = int(entered.timestamp())
        except ValueError:
            return {"mfe_pct": None, "mae_pct": None, "available_move_pct": None}
        entry_bucket = entered_ts // 60 * 60
        rows = [x for x in self.bars if int(x.get("ts", 0)) >= entry_bucket]
        if not rows:
            return {"mfe_pct": None, "mae_pct": None, "available_move_pct": None}
        high = max(float(x["high"]) for x in rows)
        low = min(float(x["low"]) for x in rows)
        side = self.position_side() or "long"
        if side == "short":
            mfe = (entry - low) / entry * 100
            mae = (entry - high) / entry * 100
        else:
            mfe = (high / entry - 1) * 100
            mae = (low / entry - 1) * 100
        return {
            "entry_price": round(entry, 8),
            "trade_high": round(high, 8),
            "trade_low": round(low, 8),
            "mfe_pct": round(mfe, 4),
            "mae_pct": round(mae, 4),
            "available_move_pct": round((high - low) / entry * 100, 4)
            if entry > 0
            else None,
            "position_side": side,
            "excursion_precision": "1m_bar_bounded",
        }

    def manage(
        self,
        *,
        btc_bias_on: bool = False,
        btc_in_position: bool = False,
    ) -> dict[str, Any] | None:
        qty = self.qty()
        if qty <= 0 or not self.mark:
            return None
        self.highest = max(self.highest, float(self.mark))
        snap = self.snapshot_strategy(
            btc_bias_on=btc_bias_on,
            btc_in_position=btc_in_position,
        )
        profile = playbook_profile(self.id)
        mode = str(
            self.entry_mode
            or snap.get("mode")
            or profile["primary"]
        )
        rate = fee_rate(
            self.id,
            qty=max(qty, 1.0),
            price=float(self.mark),
            side="sell",
        )
        cost_pct = max(
            float(snap.get("cost_pct") or 0.0),
            rate * 200,
        )
        if mode == "daily_swing":
            source_bars = list(self.bars_1d)
        elif mode == "swing":
            source_bars = list(self.bars_1h)
        else:
            source_bars = resample_bars(
                list(self.bars),
                15,
                require_complete=True,
            )
        plan = exit_plan(
            list(self.bars),
            self.wallet.avg_entry(self.id),
            self.highest,
            self.mark,
            float(profile["max_stop_pct"]),
            cost_pct,
            frozen_hard_stop=self.stop,
            source_bars=source_bars or None,
            minimum_stop_pct=float(profile["min_stop_pct"]),
            atr_multiplier=2.0,
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
        limit = (
            profile.get("time_stop_minutes") or {}
        ).get(mode)
        timed = bool(
            limit is not None
            and time_stop_due(
                held,
                gain,
                cost_pct,
                limit=int(limit),
            )
        )
        rule_exit = snap.get("exit_signal") == "sell"
        if not (hit or timed or rule_exit):
            return None
        exit_reference = (
            float(self.stop)
            if hit and self.stop
            else float(self.bid if self.bid is not None else self.mark)
        )
        raw = stop_fill_price(self.stop) if hit and self.stop else self.fill_px("sell")
        if not raw:
            return None
        buy_fill = next(
            (
                fill
                for fill in reversed(self.fills)
                if str(fill.get("side") or "").lower() == "buy"
            ),
            None,
        )
        entry_fill_price = float(
            (buy_fill or {}).get("price")
            or avg
            or 0.0
        )
        entry_reference = float(
            (buy_fill or {}).get("reference_price")
            or entry_fill_price
            or 0.0
        )
        entry_fee = float((buy_fill or {}).get("fee") or 0.0)
        entry_slippage_usd = float(
            (buy_fill or {}).get("slippage_usd") or 0.0
        )
        excursion = self.current_excursion(entry_fill_price)
        result = self.wallet.sell(self.id, qty, raw)
        result["pair"] = self.pair
        result.update(excursion)

        exit_fee = float(result.get("fee") or 0.0)
        exit_slippage_usd = max(exit_reference - raw, 0.0) * qty
        exit_slippage_bps = (
            (1 - raw / exit_reference) * 10_000
            if exit_reference > 0
            else None
        )
        entry_cost = entry_fill_price * qty + entry_fee
        net_return_pct = (
            float(result.get("pnl") or 0) / entry_cost * 100
            if entry_cost > 0
            else 0.0
        )
        gross_return_pct = (
            (raw / entry_fill_price - 1) * 100
            if entry_fill_price > 0
            else 0.0
        )
        reference_return_pct = (
            (exit_reference / entry_reference - 1) * 100
            if entry_reference > 0 and exit_reference > 0
            else gross_return_pct
        )
        result["entry_fill_price"] = round(entry_fill_price, 8)
        result["exit_fill_price"] = round(raw, 8)
        result["entry_reference_price"] = round(entry_reference, 8)
        result["exit_reference_price"] = round(exit_reference, 8)
        result["entry_slippage_usd"] = round(entry_slippage_usd, 8)
        result["exit_slippage_usd"] = round(exit_slippage_usd, 8)
        result["slippage_usd"] = round(
            entry_slippage_usd + exit_slippage_usd,
            8,
        )
        result["exit_slippage_bps"] = (
            None
            if exit_slippage_bps is None
            else round(exit_slippage_bps, 4)
        )
        result["fees_usd"] = round(entry_fee + exit_fee, 8)
        result["gross_return_pct"] = round(gross_return_pct, 4)
        result["reference_return_pct"] = round(reference_return_pct, 4)
        result["net_return_pct"] = round(net_return_pct, 4)
        result["fee_drag_pct"] = round(gross_return_pct - net_return_pct, 4)
        result["slippage_drag_pct"] = round(
            reference_return_pct - gross_return_pct,
            4,
        )
        result["cost_drag_pct"] = round(
            reference_return_pct - net_return_pct,
            4,
        )

        mfe = excursion.get("mfe_pct")
        result["capture_efficiency_pct"] = (
            round(net_return_pct / float(mfe) * 100, 2)
            if mfe is not None and float(mfe) > 1e-9
            else None
        )
        result["missed_opportunity_pct"] = (
            round(max(float(mfe) - gross_return_pct, 0.0), 4)
            if mfe is not None
            else None
        )
        result["net_missed_opportunity_pct"] = (
            round(max(float(mfe) - net_return_pct, 0.0), 4)
            if mfe is not None
            else None
        )
        high = excursion.get("trade_high")
        low = excursion.get("trade_low")
        if (
            high is not None
            and low is not None
            and float(high) > float(low)
        ):
            span = float(high) - float(low)
            result["entry_efficiency_pct"] = round(
                max(
                    0.0,
                    min(
                        100.0,
                        (float(high) - entry_fill_price) / span * 100,
                    ),
                ),
                2,
            )
            result["exit_efficiency_pct"] = round(
                max(
                    0.0,
                    min(
                        100.0,
                        (raw - float(low)) / span * 100,
                    ),
                ),
                2,
            )
        else:
            result["entry_efficiency_pct"] = None
            result["exit_efficiency_pct"] = None
        result["net_capture_pct"] = result["net_return_pct"]
        result["actor"] = (
            "bot-playbook-managed-stop"
            if hit
            else "bot-playbook-rule-exit"
            if rule_exit
            else "bot-playbook-time-stop"
        )
        result["entry_mode"] = mode
        if result.get("ok"):
            self.entry_at = None
            self.entry_mode = None
            self.stop = 0.0
            self.fills.append({**result, "side": "sell", "ts": _now()})
        return result

    def capture_snapshot(self) -> dict[str, Any]:
        current = self.current_excursion()
        if self.qty() > 0:
            high = current.get("trade_high")
            low = current.get("trade_low")
            entry = current.get("entry_price")
            entry_efficiency = None
            if (
                high is not None
                and low is not None
                and entry is not None
                and float(high) > float(low)
            ):
                entry_efficiency = round(
                    max(
                        0.0,
                        min(
                            100.0,
                            (float(high) - float(entry))
                            / (float(high) - float(low))
                            * 100,
                        ),
                    ),
                    2,
                )
            return {
                "state": "open",
                **current,
                "entry_efficiency_pct": entry_efficiency,
                "exit_efficiency_pct": None,
                "gross_return_pct": None,
                "reference_return_pct": None,
                "net_return_pct": None,
                "net_capture_pct": None,
                "capture_efficiency_pct": None,
                "missed_opportunity_pct": None,
                "net_missed_opportunity_pct": None,
                "fees_usd": None,
                "slippage_usd": None,
                "cost_drag_pct": None,
            }
        sells = [
            f for f in self.fills
            if str(f.get("side", "")).lower() == "sell"
        ]
        if not sells:
            return {
                "state": "none",
                "mfe_pct": None,
                "mae_pct": None,
                "available_move_pct": None,
                "entry_efficiency_pct": None,
                "exit_efficiency_pct": None,
                "gross_return_pct": None,
                "reference_return_pct": None,
                "net_return_pct": None,
                "net_capture_pct": None,
                "capture_efficiency_pct": None,
                "missed_opportunity_pct": None,
                "net_missed_opportunity_pct": None,
                "fees_usd": None,
                "slippage_usd": None,
                "cost_drag_pct": None,
            }
        last = sells[-1]
        return {
            "state": "last_closed",
            "mfe_pct": last.get("mfe_pct"),
            "mae_pct": last.get("mae_pct"),
            "available_move_pct": last.get("available_move_pct"),
            "entry_efficiency_pct": last.get("entry_efficiency_pct"),
            "exit_efficiency_pct": last.get("exit_efficiency_pct"),
            "gross_return_pct": last.get("gross_return_pct"),
            "reference_return_pct": last.get("reference_return_pct"),
            "net_return_pct": last.get("net_return_pct"),
            "net_capture_pct": last.get("net_capture_pct"),
            "capture_efficiency_pct": last.get("capture_efficiency_pct"),
            "missed_opportunity_pct": last.get("missed_opportunity_pct"),
            "net_missed_opportunity_pct": last.get(
                "net_missed_opportunity_pct"
            ),
            "fees_usd": last.get("fees_usd"),
            "slippage_usd": last.get("slippage_usd"),
            "fee_drag_pct": last.get("fee_drag_pct"),
            "slippage_drag_pct": last.get("slippage_drag_pct"),
            "cost_drag_pct": last.get("cost_drag_pct"),
            "entry_fill_price": last.get("entry_fill_price"),
            "exit_fill_price": last.get("exit_fill_price"),
            "closed_at": last.get("ts"),
        }

    def analytics(self) -> dict[str, Any]:
        sells = [f for f in self.fills if str(f.get("side", "")).lower() == "sell"]
        wins = sum(1 for f in sells if float(f.get("pnl") or 0) > 1e-9)
        losses = sum(1 for f in sells if float(f.get("pnl") or 0) < -1e-9)
        realized = sum(float(f.get("pnl") or 0) for f in sells)
        fees = sum(float(f.get("fee") or 0) for f in self.fills)
        gross_profit = sum(max(float(f.get("pnl") or 0), 0.0) for f in sells)
        gross_loss = sum(abs(min(float(f.get("pnl") or 0), 0.0)) for f in sells)
        first = float(self.bars[0]["close"]) if self.bars else 0.0
        last = float(self.mark or (self.bars[-1]["close"] if self.bars else 0.0))
        change_pct = ((last / first) - 1) * 100 if first > 0 and last > 0 else 0.0
        return {
            "trades": len(sells),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / max(wins + losses, 1) * 100, 2),
            "realized_pnl": round(realized, 4),
            "fees": round(fees, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "profit_factor": (
                round(gross_profit / gross_loss, 4) if gross_loss > 1e-12 else None
            ),
            "change_pct": round(change_pct, 4),
        }

    def view(self) -> dict[str, Any]:
        qty = self.qty()
        avg = self.wallet.avg_entry(self.id)
        return {
            "id": self.id,
            "name": self.name,
            "symbol": self.symbol,
            "pair": self.pair,
            "kraken": self.kraken,
            "tv": self.tv,
            "mark": self.mark,
            "bid": self.bid,
            "ask": self.ask,
            "watch_last": self.watch_last,
            "open_24h": self.open_24h,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "volume_24h": self.volume_24h,
            "vwap_24h": self.vwap_24h,
            "trades_24h": self.trades_24h,
            "qty": qty,
            "avg": avg,
            "stop": self.stop or None,
            "position_value": qty * float(self.mark or 0.0),
            "open_pnl": (self.mark - avg) * qty if qty and self.mark else 0.0,
            "bars": len(self.bars),
            "context_bars_1h": len(self.bars_1h),
            "context_bars_1d": len(self.bars_1d),
            "entry_mode": self.entry_mode,
            "last_entry_signal_key": self.last_entry_signal_key,
            "broker": self.broker,
            "playbook": playbook_profile(self.id),
            "signal": self.signal,
            "reason": self.last_reason,
            "paper": True,
        }
