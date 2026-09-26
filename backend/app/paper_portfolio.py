"""Instrument-aware paper portfolio used by Aether's official 12-book desk."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import uuid
from typing import Any

from app.fees import TAKER_FEE, fee_quote
from app.fill_model import (
    SLIPPAGE_BPS,
    market_reference_price,
    modeled_fill_price,
    quote_reference_price,
)
from app.instruments import (
    instrument_spec,
    quantity_metadata,
    supports_side,
)
from app.sleeves import SleeveBook, sleeve_for_asset
from app.wallet import STARTING_USD


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _round_step(value: float, step: float) -> float:
    value = max(float(value), 0.0)
    step = max(float(step), 1e-12)
    units = math.floor(value / step + 1e-12)
    return units * step


def strategy_position_key(asset_id: str, horizon: str) -> str:
    aid = str(asset_id).lower().strip()
    route = str(horizon).lower().strip()
    if not aid or not route:
        raise ValueError("asset_id_and_horizon_required")
    return f"{aid}:{route}"


class PaperPortfolio:
    """One paper account with product-specific P/L and margin semantics."""

    def __init__(self, usd: float = STARTING_USD) -> None:
        self.starting_usd = float(usd)
        self.usd = float(usd)
        self.sleeves = SleeveBook.seed(float(usd))
        self.test_overflow_usd = 0.0
        self.positions: dict[str, dict[str, Any]] = {}
        self.closed_trades: list[dict[str, Any]] = []

    @property
    def units(self) -> dict[str, float]:
        return {
            key: abs(float(pos.get("quantity") or 0.0))
            for key, pos in self.positions.items()
        }

    @property
    def avg(self) -> dict[str, float]:
        return {
            key: float(pos.get("entry_price") or 0.0)
            for key, pos in self.positions.items()
        }

    def _position_items_for_asset(
        self,
        asset_id: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        aid = str(asset_id).lower()
        return [
            (key, pos)
            for key, pos in self.positions.items()
            if str(pos.get("asset_id") or key).lower() == aid
        ]

    def _resolve_position_key(
        self,
        asset_id: str,
        position_key: str | None = None,
    ) -> str | None:
        aid = str(asset_id).lower()
        if position_key is not None:
            key = str(position_key).lower()
            return key if key in self.positions else None
        if aid in self.positions:
            return aid
        matches = self._position_items_for_asset(aid)
        if len(matches) == 1:
            return matches[0][0]
        return None

    def _position_rows(
        self,
        asset_id: str,
        position_key: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        aid = str(asset_id).lower()
        if position_key is not None:
            key = str(position_key).lower()
            row = self.positions.get(key)
            return [(key, row)] if row is not None else []
        key = self._resolve_position_key(aid)
        if key is not None:
            row = self.positions.get(key)
            return [(key, row)] if row is not None else []
        return self._position_items_for_asset(aid)

    def positions_for_asset(
        self,
        asset_id: str,
    ) -> list[dict[str, Any]]:
        return [
            dict(pos)
            for _, pos in self._position_items_for_asset(asset_id)
        ]

    def qty(
        self,
        asset_id: str,
        *,
        position_key: str | None = None,
    ) -> float:
        if position_key is not None:
            pos = self.positions.get(
                str(position_key).lower()
            ) or {}
            return abs(
                float(pos.get("quantity") or 0.0)
            )
        key = self._resolve_position_key(asset_id)
        if key is not None:
            pos = self.positions.get(key) or {}
            return abs(
                float(pos.get("quantity") or 0.0)
            )
        return sum(
            abs(float(pos.get("quantity") or 0.0))
            for _, pos in self._position_items_for_asset(asset_id)
        )

    def avg_entry(
        self,
        asset_id: str,
        *,
        position_key: str | None = None,
    ) -> float:
        if position_key is not None:
            pos = self.positions.get(
                str(position_key).lower()
            ) or {}
            return float(
                pos.get("entry_price") or 0.0
            )
        key = self._resolve_position_key(asset_id)
        if key is not None:
            pos = self.positions.get(key) or {}
            return float(
                pos.get("entry_price") or 0.0
            )
        rows = self._position_items_for_asset(asset_id)
        total_qty = sum(
            abs(float(pos.get("quantity") or 0.0))
            for _, pos in rows
        )
        if total_qty <= 0:
            return 0.0
        return (
            sum(
                abs(float(pos.get("quantity") or 0.0))
                * float(pos.get("entry_price") or 0.0)
                for _, pos in rows
            )
            / total_qty
        )

    def side(
        self,
        asset_id: str,
        *,
        position_key: str | None = None,
    ) -> str | None:
        if position_key is not None:
            value = str(
                (
                    self.positions.get(
                        str(position_key).lower()
                    )
                    or {}
                ).get("side")
                or ""
            ).lower()
            return (
                value
                if value in {"long", "short"}
                else None
            )
        key = self._resolve_position_key(asset_id)
        if key is not None:
            value = str(
                (self.positions.get(key) or {}).get("side") or ""
            ).lower()
            return value if value in {"long", "short"} else None
        sides = {
            str(pos.get("side") or "").lower()
            for _, pos in self._position_items_for_asset(asset_id)
            if str(pos.get("side") or "").lower()
            in {"long", "short"}
        }
        return next(iter(sides)) if len(sides) == 1 else None

    def position(
        self,
        asset_id: str,
        *,
        position_key: str | None = None,
    ) -> dict[str, Any] | None:
        if position_key is not None:
            row = self.positions.get(
                str(position_key).lower()
            )
            return dict(row) if row else None
        key = self._resolve_position_key(asset_id)
        row = (
            self.positions.get(key)
            if key is not None
            else None
        )
        return dict(row) if row else None

    def rekey_position(
        self,
        old_key: str,
        new_key: str,
    ) -> bool:
        source = str(old_key).lower()
        target = str(new_key).lower()
        if source not in self.positions or target in self.positions:
            return False
        row = self.positions.pop(source)
        row["position_key"] = target
        row["legacy_position_key_migrated"] = True
        self.positions[target] = row
        return True

    def can_buy(self, amount: float) -> bool:
        return float(amount) > 0 and self.usd + 1e-9 >= float(amount)

    def sleeve_cash(self, asset_id: str) -> float:
        return float(self.sleeves.sleeve_for(asset_id).cash_available_usd)

    def can_buy_asset(self, asset_id: str, amount: float) -> bool:
        need = float(amount)
        return (
            need > 0
            and self.sleeves.sleeve_for(asset_id).cash_available_usd + 1e-9 >= need
        )

    def _execution_fee(
        self,
        asset_id: str,
        quantity: float,
        price: float,
        execution_side: str,
    ) -> float:
        aid = str(asset_id).lower()
        spec = instrument_spec(aid)
        kind = spec["product_type"]
        qty = abs(float(quantity))
        px = float(price)
        if kind == "crypto_spot":
            return abs(qty * px) * float(TAKER_FEE)
        if kind == "fx":
            return 0.0
        quote = fee_quote(
            aid,
            qty=qty,
            price=px,
            side=str(execution_side).lower(),
        )
        return float(quote.get("fee_usd") or 0.0)

    def _entry_fee(
        self,
        asset_id: str,
        quantity: float,
        price: float,
        side: str,
    ) -> float:
        execution_side = (
            "sell"
            if str(side).lower() == "short"
            else "buy"
        )
        return self._execution_fee(
            asset_id,
            quantity,
            price,
            execution_side,
        )

    def _exit_fee(
        self,
        asset_id: str,
        quantity: float,
        price: float,
        side: str,
    ) -> float:
        execution_side = (
            "buy"
            if str(side).lower() == "short"
            else "sell"
        )
        return self._execution_fee(
            asset_id,
            quantity,
            price,
            execution_side,
        )

    def quantity_notional_usd(
        self,
        asset_id: str,
        quantity: float,
        price: float,
    ) -> float:
        aid = str(asset_id).lower()
        spec = instrument_spec(aid)
        kind = spec["product_type"]
        qty = abs(float(quantity))
        px = abs(float(price))
        if kind in {"crypto_spot", "equity"}:
            return qty * px
        if kind == "future":
            return (
                qty
                * px
                * float(spec["point_value_usd"])
            )
        if kind == "fx":
            if spec.get("base_currency") == "USD":
                return qty
            if spec.get("quote_currency") == "USD":
                return qty * px
            return qty * px
        return qty * px

    def execution_leg_cost(
        self,
        asset_id: str,
        *,
        execution_side: str,
        quantity: float,
        bid: float | None,
        ask: float | None,
        mark: float | None,
        slippage_bps: float = SLIPPAGE_BPS,
    ) -> dict[str, Any]:
        aid = str(asset_id).lower()
        side = str(execution_side).lower()
        qty = abs(float(quantity))
        market_reference = market_reference_price(
            bid=bid,
            ask=ask,
            mark=mark,
        )
        quote_reference = quote_reference_price(
            side,
            bid=bid,
            ask=ask,
            mark=mark,
        )
        fill_price = modeled_fill_price(
            side,
            bid=bid,
            ask=ask,
            mark=mark,
            slippage_bps=slippage_bps,
        )
        if (
            qty <= 0
            or market_reference is None
            or quote_reference is None
            or fill_price is None
        ):
            return {
                "ok": False,
                "error": "execution_cost_unavailable",
            }

        adverse_side = (
            "long"
            if side == "buy"
            else "short"
        )
        spread_usd = max(
            float(
                self.move_pnl(
                    aid,
                    side=adverse_side,
                    quantity=qty,
                    entry_price=market_reference,
                    mark=quote_reference,
                )
            ),
            0.0,
        )
        slippage_usd = max(
            float(
                self.move_pnl(
                    aid,
                    side=adverse_side,
                    quantity=qty,
                    entry_price=quote_reference,
                    mark=fill_price,
                )
            ),
            0.0,
        )
        fee_usd = self._execution_fee(
            aid,
            qty,
            fill_price,
            side,
        )
        notional = self.quantity_notional_usd(
            aid,
            qty,
            market_reference,
        )
        total = spread_usd + slippage_usd + fee_usd
        return {
            "ok": True,
            "execution_side": side,
            "market_reference_price": float(
                market_reference
            ),
            "quote_reference_price": float(
                quote_reference
            ),
            "fill_price": float(fill_price),
            "quantity": qty,
            "notional_usd": float(notional),
            "spread_usd": float(spread_usd),
            "slippage_usd": float(slippage_usd),
            "fee_usd": float(fee_usd),
            "total_cost_usd": float(total),
        }

    def round_trip_cost_estimate(
        self,
        asset_id: str,
        *,
        position_side: str,
        quantity: float,
        bid: float | None,
        ask: float | None,
        mark: float | None,
        slippage_bps: float = SLIPPAGE_BPS,
    ) -> dict[str, Any]:
        side = str(position_side).lower()
        entry_execution = (
            "sell" if side == "short" else "buy"
        )
        exit_execution = (
            "buy" if side == "short" else "sell"
        )
        entry = self.execution_leg_cost(
            asset_id,
            execution_side=entry_execution,
            quantity=quantity,
            bid=bid,
            ask=ask,
            mark=mark,
            slippage_bps=slippage_bps,
        )
        exit_leg = self.execution_leg_cost(
            asset_id,
            execution_side=exit_execution,
            quantity=quantity,
            bid=bid,
            ask=ask,
            mark=mark,
            slippage_bps=slippage_bps,
        )
        if not entry.get("ok") or not exit_leg.get("ok"):
            return {
                "ok": False,
                "error": "execution_cost_unavailable",
            }
        notional = max(
            float(entry.get("notional_usd") or 0.0),
            1e-12,
        )
        spread = float(entry["spread_usd"]) + float(
            exit_leg["spread_usd"]
        )
        slippage = float(
            entry["slippage_usd"]
        ) + float(exit_leg["slippage_usd"])
        fees = float(entry["fee_usd"]) + float(
            exit_leg["fee_usd"]
        )
        total = spread + slippage + fees
        return {
            "ok": True,
            "entry": entry,
            "exit": exit_leg,
            "notional_usd": notional,
            "spread_usd": spread,
            "slippage_usd": slippage,
            "fees_usd": fees,
            "total_cost_usd": total,
            "cost_pct": total / notional * 100.0,
        }

    @staticmethod
    def _fx_pnl(spec: dict[str, Any], side: str, quantity: float, entry: float, mark: float) -> float:
        direction = 1.0 if side == "long" else -1.0
        quote_pnl = direction * (mark - entry) * quantity
        if spec.get("quote_currency") == "USD":
            return quote_pnl
        if spec.get("quote_currency") == "JPY":
            return quote_pnl / mark if mark > 0 else 0.0
        raise ValueError("unsupported FX quote conversion")

    def move_pnl(
        self,
        asset_id: str,
        *,
        side: str,
        quantity: float,
        entry_price: float,
        mark: float,
    ) -> float:
        aid = str(asset_id).lower()
        spec = instrument_spec(aid)
        side = str(side).lower()
        qty = abs(float(quantity))
        entry = float(entry_price)
        mark = float(mark)
        direction = 1.0 if side == "long" else -1.0
        kind = spec["product_type"]
        if kind in {"crypto_spot", "equity"}:
            return direction * (mark - entry) * qty
        if kind == "future":
            return direction * (mark - entry) * qty * float(spec["point_value_usd"])
        if kind == "fx":
            return self._fx_pnl(spec, side, qty, entry, mark)
        raise ValueError(f"unsupported product type: {kind}")

    def gross_pnl(
        self,
        asset_id: str,
        mark: float,
        *,
        position_key: str | None = None,
    ) -> float:
        aid = str(asset_id).lower()
        rows = self._position_rows(
            aid,
            position_key,
        )
        return sum(
            self.move_pnl(
                aid,
                side=str(pos["side"]),
                quantity=float(pos["quantity"]),
                entry_price=float(pos["entry_price"]),
                mark=float(mark),
            )
            for _, pos in rows
        )

    def open_pnl(
        self,
        asset_id: str,
        mark: float,
        *,
        position_key: str | None = None,
    ) -> float:
        aid = str(asset_id).lower()
        rows = self._position_rows(
            aid,
            position_key,
        )
        return sum(
            self.move_pnl(
                aid,
                side=str(pos["side"]),
                quantity=float(pos["quantity"]),
                entry_price=float(pos["entry_price"]),
                mark=float(mark),
            )
            - float(pos.get("entry_fee_usd") or 0.0)
            for _, pos in rows
        )

    def notional_usd(
        self,
        asset_id: str,
        mark: float | None = None,
        *,
        position_key: str | None = None,
    ) -> float:
        aid = str(asset_id).lower()
        rows = self._position_rows(
            aid,
            position_key,
        )
        spec = instrument_spec(aid)
        kind = spec["product_type"]
        total = 0.0
        for _, pos in rows:
            qty = float(pos["quantity"])
            price = float(
                mark if mark is not None else pos["entry_price"]
            )
            if kind in {"crypto_spot", "equity"}:
                total += abs(qty * price)
            elif kind == "future":
                total += abs(
                    qty
                    * price
                    * float(spec["point_value_usd"])
                )
            elif kind == "fx":
                if spec.get("base_currency") == "USD":
                    total += abs(qty)
                elif spec.get("quote_currency") == "USD":
                    total += abs(qty * price)
                else:
                    total += abs(qty * price)
            else:
                total += abs(qty * price)
        return total

    def _required_margin(
        self,
        asset_id: str,
        side: str,
        quantity: float,
        price: float,
    ) -> float:
        spec = instrument_spec(asset_id)
        kind = spec["product_type"]
        notional = (
            abs(quantity * price)
            if kind in {"crypto_spot", "equity"}
            else abs(quantity * price * float(spec.get("point_value_usd") or 1.0))
            if kind == "future"
            else abs(quantity)
            if spec.get("base_currency") == "USD"
            else abs(quantity * price)
        )
        if kind == "crypto_spot":
            return notional
        if kind == "equity" and side == "long":
            return notional
        if kind == "equity":
            return notional * float(spec.get("paper_short_margin_rate") or 0.50)
        return notional * float(spec.get("paper_margin_rate") or 0.05)

    def size_for_risk(
        self,
        asset_id: str,
        *,
        side: str,
        risk_usd: float,
        entry_price: float,
        stop_price: float,
        max_capital_usd: float | None = None,
    ) -> float:
        aid = str(asset_id).lower()
        spec = instrument_spec(aid)
        if not supports_side(aid, side):
            return 0.0
        risk = max(float(risk_usd), 0.0)
        entry = float(entry_price)
        stop = float(stop_price)
        distance = abs(entry - stop)
        if risk <= 0 or entry <= 0 or distance <= 0:
            return 0.0
        kind = spec["product_type"]
        if kind in {"crypto_spot", "equity"}:
            per_unit = distance
        elif kind == "future":
            per_unit = distance * float(spec["point_value_usd"])
            per_unit += self._entry_fee(aid, 1.0, entry, side)
            per_unit += self._exit_fee(aid, 1.0, stop, side)
        elif kind == "fx":
            if spec.get("quote_currency") == "USD":
                per_unit = distance
            elif spec.get("quote_currency") == "JPY":
                per_unit = distance / entry
            else:
                return 0.0
        else:
            return 0.0
        if per_unit <= 0:
            return 0.0
        raw = risk / per_unit
        if max_capital_usd is not None:
            cap = max(float(max_capital_usd), 0.0)
            margin_per_unit = self._required_margin(
                aid,
                side,
                1.0,
                entry,
            )
            if margin_per_unit > 0:
                raw = min(raw, cap / margin_per_unit)
        hard_max = spec.get("max_quantity")
        if hard_max is not None:
            raw = min(raw, max(float(hard_max), 0.0))
        step = float(spec.get("quantity_step") or 1.0)
        return _round_step(raw, step)

    def stop_risk_usd(
        self,
        asset_id: str,
        *,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float | None,
    ) -> float:
        if stop_price is None:
            return 0.0
        stop = float(stop_price)
        entry = float(entry_price)
        qty = abs(float(quantity))
        if stop <= 0 or entry <= 0 or qty <= 0:
            return 0.0
        pnl_at_stop = self.move_pnl(
            str(asset_id).lower(),
            side=str(side).lower(),
            quantity=qty,
            entry_price=entry,
            mark=stop,
        )
        return max(-float(pnl_at_stop), 0.0)

    def position_stop_risk_usd(
        self,
        asset_id: str,
        *,
        position_key: str | None = None,
    ) -> float:
        aid = str(asset_id).lower()
        rows = self._position_rows(
            aid,
            position_key,
        )
        total = 0.0
        for _, pos in rows:
            total += self.stop_risk_usd(
                aid,
                side=str(pos.get("side") or ""),
                quantity=float(pos.get("quantity") or 0.0),
                entry_price=float(pos.get("entry_price") or 0.0),
                stop_price=(
                    pos.get("current_stop")
                    if pos.get("current_stop") is not None
                    else pos.get("initial_stop")
                ),
            )
        return total

    def required_margin(
        self,
        asset_id: str,
        *,
        side: str,
        quantity: float,
        price: float,
    ) -> float:
        return self._required_margin(
            str(asset_id).lower(),
            str(side).lower(),
            float(quantity),
            float(price),
        )

    def open_position(
        self,
        asset_id: str,
        *,
        side: str,
        quantity: float,
        price: float,
        stop_price: float | None = None,
        mode: str | None = None,
        signal_key: str | None = None,
        opened_at: str | None = None,
        reference_price: float | None = None,
        market_reference_price: float | None = None,
        quote_reference_price: float | None = None,
        entry_spread_usd: float | None = None,
        entry_slippage_usd: float | None = None,
        modeled_round_trip_cost_usd: float | None = None,
        modeled_round_trip_cost_pct: float | None = None,
        cost_hurdle_pct: float | None = None,
        opportunity_pct: float | None = None,
        metadata: dict[str, Any] | None = None,
        execution_test: bool = False,
        position_key: str | None = None,
        sleeve_debit_already_applied: bool = False,
    ) -> dict[str, Any]:
        aid = str(asset_id).lower()
        key = str(position_key or aid).lower()
        side = str(side).lower()
        if key in self.positions:
            return {
                "ok": False,
                "error": "position_already_open",
                "asset_id": aid,
                "position_key": key,
            }
        if not supports_side(aid, side):
            return {"ok": False, "error": "side_not_supported", "asset_id": aid, "side": side}
        spec = instrument_spec(aid)
        step = float(spec.get("quantity_step") or 1.0)
        requested_qty = _round_step(float(quantity), step)
        hard_max = spec.get("max_quantity")
        qty = requested_qty
        hard_cap_applied = False
        if hard_max is not None:
            max_qty = _round_step(float(hard_max), step)
            if qty > max_qty:
                qty = max_qty
                hard_cap_applied = True
        price = float(price)
        if qty <= 0 or price <= 0:
            return {"ok": False, "error": "bad_qty_or_price", "asset_id": aid}
        fee = self._entry_fee(aid, qty, price, side)
        normal_margin = self._required_margin(aid, side, qty, price)
        margin = normal_margin
        debit = margin + fee
        sleeve_id = sleeve_for_asset(aid)
        sleeve = self.sleeves.sleeve(sleeve_id)
        if (
            not sleeve_debit_already_applied
            and sleeve.cash_available_usd + 1e-9 < debit
            and not execution_test
        ):
            return {
                "ok": False,
                "error": "insufficient_capital",
                "need": debit,
                "have": sleeve.cash_available_usd,
                "asset_id": aid,
                "sleeve_id": sleeve_id,
            }
        test_overflow = 0.0
        if self.usd + 1e-9 < debit:
            if not execution_test:
                return {
                    "ok": False,
                    "error": "insufficient_usd",
                    "need": debit,
                    "have": self.usd,
                    "asset_id": aid,
                }
            # Matrix coverage may borrow explicit test-only buying power, but
            # the position still reserves its configured paper margin in full.
            test_overflow = max(debit - self.usd, 0.0)
            self.test_overflow_usd += test_overflow
            self.usd += test_overflow
        self.usd -= debit
        if not sleeve_debit_already_applied:
            if sleeve.cash_available_usd + 1e-9 < debit and execution_test:
                # Legacy execution-validation may borrow explicit test-only buying
                # power globally; do not mint broker-local sleeve cash.
                sleeve_debit = max(sleeve.cash_available_usd, 0.0)
            else:
                sleeve_debit = debit
            sleeve.cash_available_usd -= sleeve_debit
            sleeve.fees_accrued_usd += fee
        trade_id = uuid.uuid4().hex
        ts = opened_at or _now()
        pos = {
            "trade_id": trade_id,
            "position_key": key,
            "sleeve_id": sleeve_id,
            "asset_id": aid,
            "product_type": spec["product_type"],
            "side": side,
            "quantity": qty,
            **quantity_metadata(aid, qty),
            "requested_quantity": requested_qty,
            "hard_quantity_cap_applied": hard_cap_applied,
            "entry_price": price,
            "entry_reference_price": float(
                market_reference_price
                or reference_price
                or price
            ),
            "entry_market_reference_price": float(
                market_reference_price
                or reference_price
                or price
            ),
            "entry_quote_price": float(
                quote_reference_price
                or reference_price
                or price
            ),
            "entry_spread_usd": float(
                entry_spread_usd or 0.0
            ),
            "entry_slippage_usd": float(
                entry_slippage_usd or 0.0
            ),
            "modeled_round_trip_cost_usd": (
                None
                if modeled_round_trip_cost_usd is None
                else float(modeled_round_trip_cost_usd)
            ),
            "modeled_round_trip_cost_pct": (
                None
                if modeled_round_trip_cost_pct is None
                else float(modeled_round_trip_cost_pct)
            ),
            "cost_hurdle_pct": (
                None
                if cost_hurdle_pct is None
                else float(cost_hurdle_pct)
            ),
            "opportunity_pct": (
                None
                if opportunity_pct is None
                else float(opportunity_pct)
            ),
            "entry_fee_usd": fee,
            "margin_reserved_usd": margin,
            "opened_at": ts,
            "mode": mode,
            "signal_key": signal_key,
            "initial_stop": float(stop_price) if stop_price else None,
            "current_stop": float(stop_price) if stop_price else None,
            "metadata": dict(metadata or {}),
            "execution_test_funded": bool(execution_test),
            "normal_required_margin_usd": normal_margin,
            "test_overflow_usd": test_overflow,
        }
        self.positions[key] = pos
        return {
            "ok": True,
            **pos,
            "price": price,
            "qty": qty,
            "fee": fee,
            "usd": self.usd,
        }

    def apply_filled_intent(
        self,
        filled: dict[str, Any],
        *,
        price: float,
    ) -> dict[str, Any]:
        """Commit a FILLED two-phase intent without debiting its sleeve twice."""
        if str(filled.get("state") or "") != "FILLED":
            return {"ok": False, "error": "intent_not_filled"}
        aid = str(filled.get("asset_id") or "").lower()
        horizon = str(filled.get("horizon") or "").lower()
        qty = float(filled.get("filled_qty") or filled.get("quantity") or 0.0)
        side = str(filled.get("side") or "").lower()
        reserved_usd = float(filled.get("reserved_usd") or 0.0)
        if not aid or not horizon or qty <= 0 or side not in {"long", "short"}:
            return {"ok": False, "error": "bad_filled_intent"}

        opened = self.open_position(
            aid,
            side=side,
            quantity=qty,
            price=float(price),
            signal_key=str(filled.get("signal_key") or "") or None,
            position_key=strategy_position_key(aid, horizon),
            sleeve_debit_already_applied=True,
        )
        if not opened.get("ok"):
            return opened

        actual_debit = float(opened.get("margin_reserved_usd") or 0.0) + float(
            opened.get("entry_fee_usd") or 0.0
        )
        leftover = max(reserved_usd - actual_debit, 0.0)
        if leftover > 0:
            self.sleeves.credit(aid, leftover)
        self.sleeves.sleeve_for(aid).fees_accrued_usd += float(
            opened.get("entry_fee_usd") or 0.0
        )
        opened["reserved_usd"] = reserved_usd
        opened["reserve_leftover_usd"] = leftover
        opened["order_intent_id"] = filled.get("order_intent_id")
        return opened

    def update_stop(
        self,
        asset_id: str,
        stop_price: float | None,
        *,
        position_key: str | None = None,
    ) -> None:
        key = self._resolve_position_key(asset_id, position_key)
        pos = self.positions.get(key) if key is not None else None
        if pos is not None:
            pos["current_stop"] = (
                float(stop_price) if stop_price else None
            )

    def close_position(
        self,
        asset_id: str,
        *,
        price: float,
        closed_at: str | None = None,
        exit_reason: str | None = None,
        reference_price: float | None = None,
        market_reference_price: float | None = None,
        quote_reference_price: float | None = None,
        exit_spread_usd: float | None = None,
        exit_slippage_usd: float | None = None,
        position_key: str | None = None,
    ) -> dict[str, Any]:
        aid = str(asset_id).lower()
        key = self._resolve_position_key(aid, position_key)
        pos = self.positions.get(key) if key is not None else None
        if not pos:
            return {
                "ok": False,
                "error": "no_position",
                "asset_id": aid,
                "position_key": position_key,
            }
        price = float(price)
        if price <= 0:
            return {"ok": False, "error": "bad_price", "asset_id": aid}
        side = str(pos["side"])
        qty = float(pos["quantity"])
        gross = self.gross_pnl(
            aid,
            price,
            position_key=key,
        )
        exit_fee = self._exit_fee(aid, qty, price, side)
        entry_fee = float(pos.get("entry_fee_usd") or 0.0)
        net = gross - entry_fee - exit_fee
        margin = float(pos.get("margin_reserved_usd") or 0.0)
        kind = str(pos["product_type"])

        if kind in {"crypto_spot", "equity"} and side == "long":
            # Cash long: reserved margin is the purchase notional. Return sale proceeds.
            close_credit = qty * price - exit_fee
            self.usd += close_credit
        else:
            # Margin/short products: release margin and realize gross P/L.
            close_credit = margin + gross - exit_fee
            self.usd += close_credit

        sleeve = self.sleeves.sleeve_for(aid)
        sleeve.cash_available_usd += close_credit
        sleeve.realized_pnl_usd += net
        sleeve.fees_accrued_usd += exit_fee

        overflow = float(pos.get("test_overflow_usd") or 0.0)
        overflow_repaid = min(max(self.usd, 0.0), overflow)
        if overflow_repaid > 0:
            self.usd -= overflow_repaid
            self.test_overflow_usd = max(
                self.test_overflow_usd - overflow_repaid,
                0.0,
            )

        ts = closed_at or _now()
        opened = _parse_ts(str(pos.get("opened_at") or ""))
        closed = _parse_ts(ts)
        duration = (
            max(int((closed - opened).total_seconds()), 0)
            if opened is not None and closed is not None
            else None
        )
        trade = {
            **pos,
            "closed_at": ts,
            "exit_price": price,
            "exit_reference_price": float(
                market_reference_price
                or reference_price
                or price
            ),
            "exit_market_reference_price": float(
                market_reference_price
                or reference_price
                or price
            ),
            "exit_quote_price": float(
                quote_reference_price
                or reference_price
                or price
            ),
            "exit_spread_usd": float(
                exit_spread_usd or 0.0
            ),
            "exit_slippage_usd": float(
                exit_slippage_usd or 0.0
            ),
            "exit_fee_usd": exit_fee,
            "fees_usd": entry_fee + exit_fee,
            "gross_pnl_usd": gross,
            "realized_pnl_usd": net,
            "exit_reason": exit_reason,
            "duration_seconds": duration,
            "status": "closed",
            "test_overflow_repaid_usd": overflow_repaid,
            "test_overflow_outstanding_usd": self.test_overflow_usd,
        }
        del self.positions[key]
        self.closed_trades.append(trade)
        return {
            "ok": True,
            **trade,
            "price": price,
            "qty": qty,
            "fee": exit_fee,
            "pnl": net,
            "usd": self.usd,
        }

    def annotate_closed_trade(
        self,
        trade_id: str,
        updates: dict[str, Any],
    ) -> None:
        target = str(trade_id or "")
        if not target:
            return
        for row in reversed(self.closed_trades):
            if str(row.get("trade_id") or "") == target:
                row.update(dict(updates))
                return

    def equity(self, marks: dict[str, float]) -> float:
        total = self.usd
        for key, pos in self.positions.items():
            aid = str(pos.get("asset_id") or key).lower()
            mark = float(
                marks.get(
                    aid,
                    pos.get("entry_price") or 0.0,
                )
                or 0.0
            )
            kind = str(pos["product_type"])
            side = str(pos["side"])
            qty = float(pos["quantity"])
            if kind in {"crypto_spot", "equity"} and side == "long":
                total += qty * mark
            else:
                total += float(
                    pos.get("margin_reserved_usd") or 0.0
                )
                total += self.move_pnl(
                    aid,
                    side=side,
                    quantity=qty,
                    entry_price=float(pos["entry_price"]),
                    mark=mark,
                )
        return total - self.test_overflow_usd

    def snapshot(self, marks: dict[str, float]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        reserved = 0.0
        gross_exposure = 0.0
        open_pnl = 0.0
        for key, pos in self.positions.items():
            aid = str(pos.get("asset_id") or key).lower()
            mark = float(
                marks.get(
                    aid,
                    pos.get("entry_price") or 0.0,
                )
                or 0.0
            )
            pnl = self.open_pnl(
                aid,
                mark,
                position_key=key,
            )
            notional = self.notional_usd(
                aid,
                mark,
                position_key=key,
            )
            margin = float(pos.get("margin_reserved_usd") or 0.0)
            reserved += margin
            gross_exposure += notional
            open_pnl += pnl
            rows.append(
                {
                    **dict(pos),
                    "mark": mark,
                    "notional_usd": notional,
                    "open_pnl_usd": pnl,
                }
            )
        return {
            "starting_usd": round(self.starting_usd, 4),
            "usd": round(self.usd, 4),
            "cash": round(self.usd, 4),
            "equity": round(self.equity(marks), 4),
            "reserved_margin_usd": round(reserved, 4),
            "free_margin_usd": round(max(self.usd, 0.0), 4),
            "available_buying_power_usd": round(max(self.usd, 0.0), 4),
            "gross_exposure_usd": round(gross_exposure, 4),
            "test_overflow_usd": round(self.test_overflow_usd, 4),
            "open_pnl_usd": round(open_pnl, 4),
            "positions": rows,
            "holdings": rows,
            "model": "instrument_aware_paper_portfolio",
        }

    def payload(self) -> dict[str, Any]:
        return {
            "starting_usd": self.starting_usd,
            "usd": self.usd,
            "test_overflow_usd": self.test_overflow_usd,
            "positions": self.positions,
            "closed_trades": self.closed_trades[-1000:],
            "sleeves": self.sleeves.payload(),
        }

    def restore(self, data: dict[str, Any]) -> None:
        target_starting_usd = float(self.starting_usd)
        saved_starting_usd = float(
            data.get("starting_usd", target_starting_usd)
        )
        saved_usd = float(data.get("usd", self.usd))
        capital_upgrade = max(target_starting_usd - saved_starting_usd, 0.0)
        self.starting_usd = max(saved_starting_usd, target_starting_usd)
        self.usd = saved_usd + capital_upgrade
        sleeve_payload = data.get("sleeves")
        if isinstance(sleeve_payload, dict):
            self.sleeves = SleeveBook.restore(
                sleeve_payload,
                fallback_starting=self.starting_usd,
            )
            if capital_upgrade > 0:
                upgraded = SleeveBook.seed(capital_upgrade)
                for sid, ledger in upgraded.ledgers.items():
                    self.sleeves.sleeve(sid).cash_available_usd += (
                        ledger.cash_available_usd
                    )
                self.sleeves.starting_usd = self.starting_usd
        else:
            self.sleeves = SleeveBook.seed(self.starting_usd)
        self.test_overflow_usd = float(data.get("test_overflow_usd", 0.0) or 0.0)
        positions = data.get("positions") or {}
        self.positions = {}
        for raw_key, raw_position in positions.items():
            if not isinstance(raw_position, dict):
                continue
            key = str(raw_key).lower()
            row = dict(raw_position)
            aid = str(
                row.get("asset_id")
                or key.split(":", 1)[0]
            ).lower()
            row["asset_id"] = aid
            row["position_key"] = str(
                row.get("position_key") or key
            ).lower()
            row.update(
                quantity_metadata(
                    aid,
                    float(row.get("quantity") or 0.0),
                )
            )
            self.positions[row["position_key"]] = row

        # Upgrade open execution-test positions created by the former
        # zero-margin experiment so restored accounting uses real paper margin.
        for pos in self.positions.values():
            if not bool(pos.get("execution_test_funded")):
                continue
            if float(pos.get("margin_reserved_usd") or 0.0) > 0:
                continue
            required = float(pos.get("normal_required_margin_usd") or 0.0)
            if required <= 0:
                continue
            overflow = max(required - self.usd, 0.0)
            if overflow > 0:
                self.test_overflow_usd += overflow
                self.usd += overflow
            self.usd -= required
            pos["margin_reserved_usd"] = required
            pos["test_overflow_usd"] = (
                float(pos.get("test_overflow_usd") or 0.0) + overflow
            )
            pos["execution_test_margin_migrated"] = True

        # One-time compatibility with the former SpotWallet payload.
        # Its cash balance already reflected the purchase debit, so migration
        # reconstructs long inventory without debiting cash a second time.
        if not self.positions and isinstance(data.get("units"), dict):
            units = data.get("units") or {}
            avgs = data.get("avg") or {}
            for raw_aid, raw_qty in units.items():
                aid = str(raw_aid).lower()
                qty = abs(float(raw_qty or 0.0))
                entry = float(avgs.get(raw_aid, avgs.get(aid, 0.0)) or 0.0)
                if qty <= 0 or entry <= 0:
                    continue
                try:
                    spec = instrument_spec(aid)
                except KeyError:
                    continue
                if spec["product_type"] not in {"crypto_spot", "equity"}:
                    continue
                self.positions[aid] = {
                    "trade_id": f"legacy-{aid}",
                    "position_key": aid,
                    "asset_id": aid,
                    "product_type": spec["product_type"],
                    "side": "long",
                    "quantity": qty,
                    **quantity_metadata(aid, qty),
                    "requested_quantity": qty,
                    "hard_quantity_cap_applied": False,
                    "entry_price": entry,
                    "entry_reference_price": entry,
                    "entry_fee_usd": 0.0,
                    "margin_reserved_usd": qty * entry,
                    "opened_at": None,
                    "mode": None,
                    "signal_key": None,
                    "initial_stop": None,
                    "current_stop": None,
                    "legacy_migrated": True,
                }

        closed = data.get("closed_trades") or []
        self.closed_trades = [
            dict(row)
            for row in closed[-1000:]
            if isinstance(row, dict)
        ]
