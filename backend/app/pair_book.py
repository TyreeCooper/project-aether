"""One Aether asset book. Own bars and strategy state, shared paper portfolio."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.clock import is_new_five_minute
from app.exits import stop_fill_price, time_stop_due
from app.execution_matrix import (
    execution_mode,
    supported_horizons,
)
from app.fees import fee_rate
from app.fill_model import (
    SLIPPAGE_BPS,
    market_reference_price,
    quote_reference_price,
)
from app.instruments import (
    instrument_spec,
    quantity_metadata,
)
from app.paper_exec import slipped_price
from app.playbooks import playbook_profile, playbook_snapshot
from app.sessions import for_asset
from app.strategy import exit_plan, resample_bars

BAR_HISTORY = 720
COST_EDGE_MULTIPLE = 1.40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PairBook:
    def __init__(
        self,
        asset: dict[str, Any],
        wallet,
        *,
        position_key: str | None = None,
        routing_horizon: str | None = None,
    ) -> None:
        self.id = str(asset["id"])
        self.position_key = (
            str(position_key).lower()
            if position_key is not None
            else None
        )
        self.routing_horizon = (
            str(routing_horizon).lower()
            if routing_horizon is not None
            else None
        )
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
        return self.wallet.qty(
            self.id,
            position_key=self.position_key,
        )

    def position_side(self) -> str | None:
        side = getattr(self.wallet, "side", None)
        return (
            side(
                self.id,
                position_key=self.position_key,
            )
            if callable(side)
            else ("long" if self.qty() > 0 else None)
        )

    def position(self) -> dict[str, Any] | None:
        getter = getattr(self.wallet, "position", None)
        if not callable(getter):
            return None
        return getter(
            self.id,
            position_key=self.position_key,
        )

    def management_contract(
        self,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = dict(position or self.position() or {})
        metadata = dict(row.get("metadata") or {})
        profile = playbook_profile(self.id)
        execution_test_position = bool(
            row.get("execution_test_funded")
            or metadata.get("execution_test")
        )

        route_horizon = None
        source = "legacy_entry_mode"
        if execution_test_position:
            management_mode = str(profile["primary"])
            source = "execution_validation_primary"
        else:
            candidates = (
                self.routing_horizon,
                metadata.get("originating_horizon"),
                metadata.get("routing_horizon"),
            )
            for candidate in candidates:
                normalized = str(candidate or "").lower()
                if normalized in set(supported_horizons(self.id)):
                    route_horizon = normalized
                    break
            if route_horizon is not None:
                management_mode = execution_mode(
                    self.id,
                    route_horizon,
                )
                source = "route_horizon"
            else:
                saved = str(
                    row.get("mode")
                    or self.entry_mode
                    or profile["primary"]
                ).lower()
                valid_modes = {
                    execution_mode(self.id, horizon)
                    for horizon in supported_horizons(self.id)
                }
                management_mode = (
                    saved
                    if saved in valid_modes
                    else str(profile["primary"])
                )

        source_clock = (
            "1d"
            if management_mode == "daily_swing"
            else "1h"
            if management_mode == "swing"
            else "1m"
            if management_mode == "scalp"
            else "15m"
        )
        time_stop_minutes = (
            profile.get("time_stop_minutes") or {}
        ).get(management_mode)

        return {
            "asset_id": self.id,
            "position_key": (
                row.get("position_key")
                or self.position_key
                or self.id
            ),
            "originating_horizon": route_horizon,
            "management_mode": management_mode,
            "management_clock": source_clock,
            "time_stop_minutes": time_stop_minutes,
            "source": source,
            "execution_test": execution_test_position,
        }

    def _management_source_bars(
        self,
        management_mode: str,
    ) -> list[dict[str, Any]]:
        mode = str(management_mode).lower()
        if mode == "daily_swing":
            return list(self.bars_1d)
        if mode == "swing":
            return list(self.bars_1h)
        if mode == "scalp":
            return list(self.bars)
        return resample_bars(
            list(self.bars),
            15,
            require_complete=True,
        )

    def snapshot_strategy(
        self,
        *,
        btc_bias_on: bool = False,
        btc_in_position: bool = False,
        requested_mode: str | None = None,
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
            requested_mode=requested_mode,
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

    def entry_plan(
        self,
        risk_usd: float,
        *,
        strategy_snapshot: dict[str, Any] | None = None,
        max_capital_usd: float | None = None,
        execution_test: bool = False,
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
        market_reference = market_reference_price(
            bid=self.bid,
            ask=self.ask,
            mark=self.mark,
        )
        quote_reference = quote_reference_price(
            fill_side,
            bid=self.bid,
            ask=self.ask,
            mark=self.mark,
        )
        px = self.fill_px(fill_side)
        if (
            market_reference is None
            or quote_reference is None
            or not px
        ):
            return {
                "ok": False,
                "error": "no_mark",
                "pair": self.pair,
            }

        stop_pct = max(
            float(snap.get("risk_stop_pct") or 2.0),
            0.01,
        )
        stop_price = (
            px * (1 + stop_pct / 100)
            if position_side == "short"
            else px * (1 - stop_pct / 100)
        )
        size_for_risk = getattr(
            self.wallet,
            "size_for_risk",
            None,
        )
        if not callable(size_for_risk):
            return {
                "ok": False,
                "error": "paper_portfolio_required",
                "pair": self.pair,
            }
        if execution_test:
            qty = float(
                instrument_spec(self.id).get("quantity_step")
                or 1.0
            )
        else:
            qty = float(
                size_for_risk(
                    self.id,
                    side=position_side,
                    risk_usd=float(risk_usd),
                    entry_price=px,
                    stop_price=stop_price,
                    max_capital_usd=max_capital_usd,
                )
                or 0.0
            )
        if qty <= 0:
            return {
                "ok": False,
                "error": "risk_size_below_minimum",
                "pair": self.pair,
            }

        risk_fn = getattr(self.wallet, "stop_risk_usd", None)
        stop_risk = (
            float(
                risk_fn(
                    self.id,
                    side=position_side,
                    quantity=qty,
                    entry_price=px,
                    stop_price=stop_price,
                )
            )
            if callable(risk_fn)
            else 0.0
        )
        route_position_key = str(
            snap.get("position_key")
            or self.position_key
            or self.id
        ).lower()

        cost_estimator = getattr(
            self.wallet,
            "round_trip_cost_estimate",
            None,
        )
        cost_model = (
            cost_estimator(
                self.id,
                position_side=position_side,
                quantity=qty,
                bid=self.bid,
                ask=self.ask,
                mark=self.mark,
                slippage_bps=SLIPPAGE_BPS,
            )
            if callable(cost_estimator)
            else {"ok": False}
        )
        opportunity_pct = float(
            snap.get("opportunity_pct") or 0.0
        )
        modeled_cost_pct = float(
            cost_model.get("cost_pct") or 0.0
        )
        cost_hurdle_pct = (
            modeled_cost_pct * COST_EDGE_MULTIPLE
        )
        if (
            not execution_test
            and opportunity_pct > 0
            and modeled_cost_pct > 0
            and opportunity_pct + 1e-12
            < cost_hurdle_pct
        ):
            return {
                "ok": False,
                "error": "edge_below_cost_hurdle",
                "pair": self.pair,
                "position_key": route_position_key,
                "opportunity_pct": opportunity_pct,
                "modeled_round_trip_cost_pct": (
                    modeled_cost_pct
                ),
                "cost_hurdle_pct": cost_hurdle_pct,
                "modeled_round_trip_cost_usd": float(
                    cost_model.get(
                        "total_cost_usd"
                    )
                    or 0.0
                ),
            }

        entry_leg = dict(
            cost_model.get("entry") or {}
        )
        return {
            "ok": True,
            "position_key": route_position_key,
            "position_side": position_side,
            "execution_side": fill_side,
            "reference_price": float(quote_reference),
            "market_reference_price": float(
                market_reference
            ),
            "quote_reference_price": float(
                quote_reference
            ),
            "price": float(px),
            "stop_price": float(stop_price),
            "risk_stop_pct": float(stop_pct),
            "qty": float(qty),
            **quantity_metadata(self.id, qty),
            "entry_spread_usd": float(
                entry_leg.get("spread_usd") or 0.0
            ),
            "entry_slippage_usd": float(
                entry_leg.get("slippage_usd") or 0.0
            ),
            "modeled_round_trip_cost_usd": float(
                cost_model.get("total_cost_usd") or 0.0
            ),
            "modeled_round_trip_cost_pct": (
                modeled_cost_pct
            ),
            "cost_hurdle_pct": cost_hurdle_pct,
            "opportunity_pct": opportunity_pct,
            "stop_risk_usd": float(stop_risk),
        }

    def enter(
        self,
        risk_usd: float,
        *,
        strategy_snapshot: dict[str, Any] | None = None,
        max_capital_usd: float | None = None,
        execution_test: bool = False,
        entry_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snap = dict(strategy_snapshot or {})
        plan = dict(
            entry_plan
            or self.entry_plan(
                risk_usd,
                strategy_snapshot=snap,
                max_capital_usd=max_capital_usd,
                execution_test=execution_test,
            )
        )
        if not plan.get("ok"):
            return plan

        position_side = str(plan["position_side"])
        fill_side = str(plan["execution_side"])
        reference = float(plan["reference_price"])
        market_reference = float(
            plan.get("market_reference_price")
            or reference
        )
        quote_reference = float(
            plan.get("quote_reference_price")
            or reference
        )
        px = float(plan["price"])
        stop_price = float(plan["stop_price"])
        stop_pct = float(plan["risk_stop_pct"])
        qty = float(plan["qty"])
        stop_risk = float(plan.get("stop_risk_usd") or 0.0)
        route_position_key = str(plan["position_key"])

        open_position = getattr(
            self.wallet,
            "open_position",
            None,
        )
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
            reference_price=market_reference,
            market_reference_price=market_reference,
            quote_reference_price=quote_reference,
            entry_spread_usd=float(
                plan.get("entry_spread_usd") or 0.0
            ),
            entry_slippage_usd=float(
                plan.get("entry_slippage_usd") or 0.0
            ),
            modeled_round_trip_cost_usd=float(
                plan.get(
                    "modeled_round_trip_cost_usd"
                )
                or 0.0
            ),
            modeled_round_trip_cost_pct=float(
                plan.get(
                    "modeled_round_trip_cost_pct"
                )
                or 0.0
            ),
            cost_hurdle_pct=float(
                plan.get("cost_hurdle_pct") or 0.0
            ),
            opportunity_pct=float(
                plan.get("opportunity_pct") or 0.0
            ),
            metadata={
                "entry_reason": snap.get("reason"),
                "quality_score": snap.get("quality_score"),
                "entry_clock": snap.get("entry_clock"),
                "bias_clock": snap.get("bias_clock"),
                "cluster": playbook_profile(self.id).get("cluster"),
                "execution_test": bool(execution_test),
                "execution_test_load": (
                    "AETHER-LOAD-002"
                    if execution_test
                    else None
                ),
                "execution_test_run": snap.get(
                    "execution_test_run"
                ),
                "would_have_blocked_by": snap.get(
                    "would_have_blocked_by"
                ),
                "normal_execution_status": snap.get(
                    "normal_execution_status"
                ),
                "normal_signal": snap.get("normal_signal"),
                "normal_quality_score": snap.get(
                    "normal_quality_score"
                ),
                "matrix_cell_id": snap.get("matrix_cell_id"),
                "matrix_horizon": snap.get("matrix_horizon"),
                "matrix_side": snap.get("matrix_side"),
                "routing_horizon": snap.get(
                    "routing_horizon"
                ),
                "originating_horizon": (
                    snap.get("routing_horizon")
                    or self.routing_horizon
                ),
                "management_mode": (
                    execution_mode(
                        self.id,
                        str(
                            snap.get("routing_horizon")
                            or self.routing_horizon
                        ),
                    )
                    if (
                        snap.get("routing_horizon")
                        or self.routing_horizon
                    )
                    else None
                ),
                "clock_horizon": snap.get("clock_horizon"),
                "strategy_id": snap.get("strategy_id"),
                "strategy_version": snap.get(
                    "strategy_version"
                ),
                "position_key": route_position_key,
                "target_risk_usd": snap.get(
                    "target_risk_usd"
                ),
                "initial_stop_risk_usd": stop_risk,
                "portfolio_open_risk_before_usd": snap.get(
                    "portfolio_open_risk_before_usd"
                ),
                "portfolio_risk_limit_usd": snap.get(
                    "portfolio_risk_limit_usd"
                ),
                "asset_open_risk_before_usd": snap.get(
                    "asset_open_risk_before_usd"
                ),
                "asset_risk_limit_usd": snap.get(
                    "asset_risk_limit_usd"
                ),
                "cluster_open_risk_before_usd": snap.get(
                    "cluster_open_risk_before_usd"
                ),
                "cluster_risk_limit_usd": snap.get(
                    "cluster_risk_limit_usd"
                ),
                "opportunity_pct": plan.get(
                    "opportunity_pct"
                ),
                "modeled_round_trip_cost_pct": plan.get(
                    "modeled_round_trip_cost_pct"
                ),
                "modeled_round_trip_cost_usd": plan.get(
                    "modeled_round_trip_cost_usd"
                ),
                "cost_hurdle_pct": plan.get(
                    "cost_hurdle_pct"
                ),
            },
            execution_test=execution_test,
            position_key=route_position_key,
        )
        result["pair"] = self.pair
        result["actor"] = "bot-playbook-entry"
        result["position_side"] = position_side
        result["execution_side"] = fill_side
        result["event"] = "entry"
        result["execution_test"] = bool(execution_test)
        result["stop_risk_usd"] = round(stop_risk, 8)
        if result.get("ok"):
            self.entry_at = str(
                result.get("opened_at") or _now()
            )
            self.entry_mode = str(
                snap.get("mode") or "intraday"
            )
            self.highest = px
            self.lowest = px
            self.stop = stop_price
            result["entry_mode"] = self.entry_mode
            result["risk_stop_pct"] = stop_pct
            signal_key = snap.get("signal_key")
            if signal_key:
                self.last_entry_signal_key = str(signal_key)
                result["signal_key"] = (
                    self.last_entry_signal_key
                )
            slippage_usd = float(
                plan.get("entry_slippage_usd") or 0.0
            )
            slippage_bps = (
                abs(px / quote_reference - 1)
                * 10_000
                if quote_reference > 0
                else None
            )
            result["reference_price"] = quote_reference
            result["market_reference_price"] = (
                market_reference
            )
            result["quote_reference_price"] = (
                quote_reference
            )
            result["spread_usd"] = round(
                float(plan.get("entry_spread_usd") or 0.0),
                8,
            )
            result["slippage_usd"] = round(
                slippage_usd,
                8,
            )
            result["modeled_round_trip_cost_usd"] = round(
                float(
                    plan.get(
                        "modeled_round_trip_cost_usd"
                    )
                    or 0.0
                ),
                8,
            )
            result["modeled_round_trip_cost_pct"] = round(
                float(
                    plan.get(
                        "modeled_round_trip_cost_pct"
                    )
                    or 0.0
                ),
                6,
            )
            result["cost_hurdle_pct"] = round(
                float(plan.get("cost_hurdle_pct") or 0.0),
                6,
            )
            result["opportunity_pct"] = round(
                float(plan.get("opportunity_pct") or 0.0),
                6,
            )
            result["slippage_bps"] = (
                None
                if slippage_bps is None
                else round(slippage_bps, 4)
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
        entry = float(
            entry_price
            or self.wallet.avg_entry(
                self.id,
                position_key=self.position_key,
            )
            or 0.0
        )
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

        side = self.position_side() or "long"
        mark = float(self.mark)
        self.highest = max(self.highest or mark, mark)
        self.lowest = min(self.lowest or mark, mark)

        profile = playbook_profile(self.id)
        position = self.position() or {}
        metadata = position.get("metadata") or {}
        contract = self.management_contract(position)
        management_mode = str(
            contract["management_mode"]
        )
        entry_mode = str(
            position.get("mode")
            or self.entry_mode
            or management_mode
        )

        snap = self.snapshot_strategy(
            btc_bias_on=btc_bias_on,
            btc_in_position=btc_in_position,
            requested_mode=management_mode,
        )
        rate = fee_rate(
            self.id,
            qty=max(qty, 1.0),
            price=mark,
            side="buy" if side == "short" else "sell",
        )
        cost_pct = max(
            float(snap.get("cost_pct") or 0.0),
            rate * 200,
        )

        source_bars = self._management_source_bars(
            management_mode
        )

        if side == "short":
            trail_pct = max(
                float(profile["min_stop_pct"]),
                min(
                    float(profile["max_stop_pct"]),
                    float(
                        snap.get("risk_stop_pct")
                        or profile["min_stop_pct"]
                    ),
                ),
            )
            candidate = self.lowest * (1 + trail_pct / 100)
            self.stop = (
                min(self.stop, candidate)
                if self.stop > 0
                else candidate
            )
        else:
            plan = exit_plan(
                list(self.bars),
                self.wallet.avg_entry(
                    self.id,
                    position_key=self.position_key,
                ),
                self.highest,
                mark,
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

        update_stop = getattr(self.wallet, "update_stop", None)
        if callable(update_stop):
            update_stop(
                self.id,
                self.stop or None,
                position_key=self.position_key,
            )

        bar_low = float(self.bars[-1]["low"]) if self.bars else mark
        bar_high = float(self.bars[-1]["high"]) if self.bars else mark
        hit = (
            self.stop > 0
            and (
                bar_high >= self.stop
                if side == "short"
                else bar_low <= self.stop
            )
        )

        held = None
        if self.entry_at:
            try:
                entered = datetime.fromisoformat(
                    self.entry_at.replace("Z", "+00:00")
                )
                held = int(
                    (
                        datetime.now(timezone.utc) - entered
                    ).total_seconds()
                    // 60
                )
            except ValueError:
                held = None

        avg = float(
            self.wallet.avg_entry(
                self.id,
                position_key=self.position_key,
            )
            or mark
        )
        notional = float(
            getattr(self.wallet, "notional_usd")(
                self.id,
                avg,
                position_key=self.position_key,
            )
        )
        move_pnl = getattr(self.wallet, "move_pnl")
        current_gross_pnl = float(
            move_pnl(
                self.id,
                side=side,
                quantity=qty,
                entry_price=avg,
                mark=mark,
            )
        )
        gain = (
            current_gross_pnl / notional * 100
            if notional > 0
            else 0.0
        )
        limit = contract.get("time_stop_minutes")
        timed = bool(
            limit is not None
            and time_stop_due(
                held,
                gain,
                cost_pct,
                limit=int(limit),
            )
        )
        rule_exit = snap.get("exit_signal") in {"sell", "exit"}
        if not (hit or timed or rule_exit):
            return None

        exit_side = "buy" if side == "short" else "sell"
        exit_reference = (
            float(self.stop)
            if hit and self.stop
            else float(
                self.ask
                if side == "short" and self.ask is not None
                else self.bid
                if side == "long" and self.bid is not None
                else mark
            )
        )
        raw = (
            stop_fill_price(
                self.stop,
                side=exit_side,
            )
            if hit and self.stop
            else self.fill_px(exit_side)
        )
        if not raw:
            return None

        entry_fill = next(
            (
                fill
                for fill in reversed(self.fills)
                if str(fill.get("event") or "") == "entry"
            ),
            None,
        )
        entry_fill_price = float(
            (entry_fill or {}).get("price")
            or avg
            or 0.0
        )
        entry_reference = float(
            (entry_fill or {}).get("reference_price")
            or entry_fill_price
            or 0.0
        )
        entry_slippage_usd = float(
            (entry_fill or {}).get("slippage_usd") or 0.0
        )
        excursion = self.current_excursion(entry_fill_price)

        close_position = getattr(self.wallet, "close_position", None)
        if not callable(close_position):
            return None
        reason = (
            "managed_stop"
            if hit
            else "rule_exit"
            if rule_exit
            else "time_stop"
        )
        result = close_position(
            self.id,
            price=float(raw),
            exit_reason=reason,
            reference_price=exit_reference,
            position_key=self.position_key,
        )
        if not result.get("ok"):
            return None
        result["pair"] = self.pair
        result.update(excursion)

        gross_pnl = float(
            move_pnl(
                self.id,
                side=side,
                quantity=qty,
                entry_price=entry_fill_price,
                mark=float(raw),
            )
        )
        reference_pnl = float(
            move_pnl(
                self.id,
                side=side,
                quantity=qty,
                entry_price=entry_reference,
                mark=exit_reference,
            )
        )
        exit_slippage_usd = max(reference_pnl - gross_pnl, 0.0)
        exit_slippage_bps = (
            abs(float(raw) / exit_reference - 1) * 10_000
            if exit_reference > 0
            else None
        )
        entry_notional = max(notional, 0.0)
        net_return_pct = (
            float(result.get("pnl") or 0.0)
            / entry_notional
            * 100
            if entry_notional > 0
            else 0.0
        )
        gross_return_pct = (
            gross_pnl / entry_notional * 100
            if entry_notional > 0
            else 0.0
        )
        reference_return_pct = (
            reference_pnl / entry_notional * 100
            if entry_notional > 0
            else gross_return_pct
        )

        result["entry_fill_price"] = round(entry_fill_price, 8)
        result["exit_fill_price"] = round(float(raw), 8)
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
        result["gross_return_pct"] = round(gross_return_pct, 4)
        result["reference_return_pct"] = round(
            reference_return_pct,
            4,
        )
        result["net_return_pct"] = round(net_return_pct, 4)
        result["fee_drag_pct"] = round(
            gross_return_pct - net_return_pct,
            4,
        )
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
            round(
                max(float(mfe) - gross_return_pct, 0.0),
                4,
            )
            if mfe is not None
            else None
        )
        result["net_missed_opportunity_pct"] = (
            round(
                max(float(mfe) - net_return_pct, 0.0),
                4,
            )
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
            if side == "short":
                entry_eff = (
                    (entry_fill_price - float(low))
                    / span
                    * 100
                )
                exit_eff = (
                    (float(high) - float(raw))
                    / span
                    * 100
                )
            else:
                entry_eff = (
                    (float(high) - entry_fill_price)
                    / span
                    * 100
                )
                exit_eff = (
                    (float(raw) - float(low))
                    / span
                    * 100
                )
            result["entry_efficiency_pct"] = round(
                max(0.0, min(100.0, entry_eff)),
                2,
            )
            result["exit_efficiency_pct"] = round(
                max(0.0, min(100.0, exit_eff)),
                2,
            )
        else:
            result["entry_efficiency_pct"] = None
            result["exit_efficiency_pct"] = None

        result["net_capture_pct"] = result["net_return_pct"]
        result["originating_horizon"] = contract.get(
            "originating_horizon"
        )
        result["management_mode"] = management_mode
        result["management_clock"] = contract.get(
            "management_clock"
        )
        result["management_time_stop_minutes"] = (
            contract.get("time_stop_minutes")
        )
        annotate = getattr(
            self.wallet,
            "annotate_closed_trade",
            None,
        )
        if callable(annotate):
            annotate(
                str(result.get("trade_id") or ""),
                {
                    "mfe_pct": result.get("mfe_pct"),
                    "mae_pct": result.get("mae_pct"),
                    "available_move_pct": result.get("available_move_pct"),
                    "capture_efficiency_pct": result.get(
                        "capture_efficiency_pct"
                    ),
                    "entry_efficiency_pct": result.get(
                        "entry_efficiency_pct"
                    ),
                    "exit_efficiency_pct": result.get(
                        "exit_efficiency_pct"
                    ),
                    "gross_return_pct": result.get("gross_return_pct"),
                    "net_return_pct": result.get("net_return_pct"),
                    "reference_return_pct": result.get(
                        "reference_return_pct"
                    ),
                    "cost_drag_pct": result.get("cost_drag_pct"),
                    "slippage_usd": result.get("slippage_usd"),
                    "entry_slippage_usd": result.get(
                        "entry_slippage_usd"
                    ),
                    "exit_slippage_usd": result.get(
                        "exit_slippage_usd"
                    ),
                    "originating_horizon": result.get(
                        "originating_horizon"
                    ),
                    "management_mode": result.get(
                        "management_mode"
                    ),
                    "management_clock": result.get(
                        "management_clock"
                    ),
                    "actor": f"bot-playbook-{reason.replace('_', '-')}",
                },
            )
        result["actor"] = f"bot-playbook-{reason.replace('_', '-')}"
        result["entry_mode"] = entry_mode
        result["position_side"] = side
        result["execution_side"] = exit_side
        result["event"] = "exit"

        closed_at = str(result.get("closed_at") or _now())
        self.entry_at = None
        self.entry_mode = None
        self.stop = 0.0
        self.highest = 0.0
        self.lowest = 0.0
        self.fills.append(
            {
                **result,
                "side": exit_side,
                "ts": closed_at,
            }
        )
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
        closes = [
            f
            for f in self.fills
            if str(f.get("event") or "") == "exit"
            or (
                not f.get("event")
                and str(f.get("side") or "").lower() == "sell"
                and f.get("pnl") is not None
            )
        ]
        if not closes:
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
        last = closes[-1]
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
        closed = [
            row
            for row in getattr(self.wallet, "closed_trades", [])
            if str(row.get("asset_id") or "") == self.id
        ]
        legacy_closed = [
            {
                "realized_pnl_usd": float(row.get("pnl") or 0.0),
                "fees_usd": float(row.get("fee") or 0.0),
                "duration_seconds": row.get("duration_seconds"),
            }
            for row in self.fills
            if not row.get("event")
            and str(row.get("side") or "").lower() == "sell"
            and row.get("pnl") is not None
        ]
        closed = closed + legacy_closed
        wins = sum(
            1
            for row in closed
            if float(row.get("realized_pnl_usd") or 0.0) > 1e-9
        )
        losses = sum(
            1
            for row in closed
            if float(row.get("realized_pnl_usd") or 0.0) < -1e-9
        )
        realized = sum(
            float(row.get("realized_pnl_usd") or 0.0)
            for row in closed
        )
        fees = sum(
            float(row.get("fees_usd") or 0.0)
            for row in closed
        )
        open_pos = self.position()
        if open_pos:
            fees += float(open_pos.get("entry_fee_usd") or 0.0)
        gross_profit = sum(
            max(float(row.get("realized_pnl_usd") or 0.0), 0.0)
            for row in closed
        )
        gross_loss = sum(
            abs(min(float(row.get("realized_pnl_usd") or 0.0), 0.0))
            for row in closed
        )
        first = float(self.bars[0]["close"]) if self.bars else 0.0
        last = float(
            self.mark
            or (self.bars[-1]["close"] if self.bars else 0.0)
        )
        change_pct = (
            ((last / first) - 1) * 100
            if first > 0 and last > 0
            else 0.0
        )
        durations = [
            float(row["duration_seconds"])
            for row in closed
            if row.get("duration_seconds") is not None
        ]
        return {
            "trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(
                wins / max(wins + losses, 1) * 100,
                2,
            ),
            "realized_pnl": round(realized, 4),
            "fees": round(fees, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "profit_factor": (
                round(gross_profit / gross_loss, 4)
                if gross_loss > 1e-12
                else None
            ),
            "avg_duration_seconds": (
                round(sum(durations) / len(durations), 2)
                if durations
                else None
            ),
            "change_pct": round(change_pct, 4),
        }

    def view(self) -> dict[str, Any]:
        qty = self.qty()
        avg = self.wallet.avg_entry(
            self.id,
            position_key=self.position_key,
        )
        side = self.position_side()
        position = self.position()
        management = (
            self.management_contract(position)
            if position
            else None
        )
        mark = float(self.mark or 0.0)
        notional = (
            float(
                getattr(self.wallet, "notional_usd")(
                    self.id,
                    mark,
                    position_key=self.position_key,
                )
            )
            if qty > 0 and hasattr(self.wallet, "notional_usd")
            else 0.0
        )
        open_pnl = (
            float(
                getattr(self.wallet, "open_pnl")(
                    self.id,
                    mark,
                    position_key=self.position_key,
                )
            )
            if qty > 0 and hasattr(self.wallet, "open_pnl")
            else 0.0
        )
        return {
            "id": self.id,
            "position_key": self.position_key,
            "routing_horizon": self.routing_horizon,
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
            "side": side,
            "avg": avg,
            "stop": self.stop or None,
            "position_value": notional,
            "open_pnl": open_pnl,
            "trade_id": (position or {}).get("trade_id"),
            "opened_at": (position or {}).get("opened_at"),
            "margin_reserved_usd": (position or {}).get(
                "margin_reserved_usd"
            ),
            "quantity_unit": (position or {}).get("quantity_unit"),
            "base_units": (position or {}).get("base_units"),
            "standard_lots": (position or {}).get("standard_lots"),
            "standard_lot_units": (position or {}).get(
                "standard_lot_units"
            ),
            "max_standard_lots": (position or {}).get(
                "max_standard_lots"
            ),
            "contracts": (position or {}).get("contracts"),
            "shares": (position or {}).get("shares"),
            "coin_quantity": (position or {}).get(
                "coin_quantity"
            ),
            "max_quantity": (position or {}).get("max_quantity"),
            "hard_quantity_cap_applied": (position or {}).get(
                "hard_quantity_cap_applied"
            ),
            "bars": len(self.bars),
            "context_bars_1h": len(self.bars_1h),
            "context_bars_1d": len(self.bars_1d),
            "entry_mode": self.entry_mode,
            "originating_horizon": (
                (management or {}).get(
                    "originating_horizon"
                )
            ),
            "management_mode": (
                (management or {}).get("management_mode")
            ),
            "management_clock": (
                (management or {}).get("management_clock")
            ),
            "management_time_stop_minutes": (
                (management or {}).get(
                    "time_stop_minutes"
                )
            ),
            "last_entry_signal_key": self.last_entry_signal_key,
            "broker": self.broker,
            "playbook": playbook_profile(self.id),
            "signal": self.signal,
            "reason": self.last_reason,
            "paper": True,
        }

