"""Instrument-aware paper portfolio used by Aether's official 12-book desk."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import uuid
from typing import Any

from app.fees import TAKER_FEE, fee_quote
from app.instruments import instrument_spec, supports_side


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


class PaperPortfolio:
    """One paper account with product-specific P/L and margin semantics."""

    def __init__(self, usd: float = 10_000.0) -> None:
        self.starting_usd = float(usd)
        self.usd = float(usd)
        self.positions: dict[str, dict[str, Any]] = {}
        self.closed_trades: list[dict[str, Any]] = []

    @property
    def units(self) -> dict[str, float]:
        return {aid: self.qty(aid) for aid in self.positions}

    @property
    def avg(self) -> dict[str, float]:
        return {aid: self.avg_entry(aid) for aid in self.positions}

    def qty(self, asset_id: str) -> float:
        pos = self.positions.get(str(asset_id).lower()) or {}
        return abs(float(pos.get("quantity") or 0.0))

    def avg_entry(self, asset_id: str) -> float:
        pos = self.positions.get(str(asset_id).lower()) or {}
        return float(pos.get("entry_price") or 0.0)

    def side(self, asset_id: str) -> str | None:
        pos = self.positions.get(str(asset_id).lower()) or {}
        value = str(pos.get("side") or "").lower()
        return value if value in {"long", "short"} else None

    def position(self, asset_id: str) -> dict[str, Any] | None:
        row = self.positions.get(str(asset_id).lower())
        return dict(row) if row else None

    def can_buy(self, amount: float) -> bool:
        return float(amount) > 0 and self.usd + 1e-9 >= float(amount)

    def _entry_fee(self, asset_id: str, quantity: float, price: float, side: str) -> float:
        spec = instrument_spec(asset_id)
        kind = spec["product_type"]
        if kind == "crypto_spot":
            return abs(quantity * price) * float(TAKER_FEE)
        if kind == "fx":
            # Bid/ask plus paper slippage carry FX transaction cost.
            return 0.0
        q = fee_quote(
            asset_id,
            qty=quantity,
            price=price,
            side="sell" if side == "short" else "buy",
        )
        return float(q.get("fee_usd") or 0.0)

    def _exit_fee(self, asset_id: str, quantity: float, price: float, side: str) -> float:
        spec = instrument_spec(asset_id)
        kind = spec["product_type"]
        if kind == "crypto_spot":
            return abs(quantity * price) * float(TAKER_FEE)
        if kind == "fx":
            return 0.0
        q = fee_quote(
            asset_id,
            qty=quantity,
            price=price,
            side="buy" if side == "short" else "sell",
        )
        return float(q.get("fee_usd") or 0.0)

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

    def gross_pnl(self, asset_id: str, mark: float) -> float:
        aid = str(asset_id).lower()
        pos = self.positions.get(aid)
        if not pos:
            return 0.0
        return self.move_pnl(
            aid,
            side=str(pos["side"]),
            quantity=float(pos["quantity"]),
            entry_price=float(pos["entry_price"]),
            mark=float(mark),
        )

    def open_pnl(self, asset_id: str, mark: float) -> float:
        pos = self.positions.get(str(asset_id).lower())
        if not pos:
            return 0.0
        return self.gross_pnl(asset_id, mark) - float(pos.get("entry_fee_usd") or 0.0)

    def notional_usd(self, asset_id: str, mark: float | None = None) -> float:
        aid = str(asset_id).lower()
        pos = self.positions.get(aid)
        if not pos:
            return 0.0
        spec = instrument_spec(aid)
        qty = float(pos["quantity"])
        price = float(mark if mark is not None else pos["entry_price"])
        kind = spec["product_type"]
        if kind in {"crypto_spot", "equity"}:
            return abs(qty * price)
        if kind == "future":
            return abs(qty * price * float(spec["point_value_usd"]))
        if kind == "fx":
            if spec.get("base_currency") == "USD":
                return abs(qty)
            if spec.get("quote_currency") == "USD":
                return abs(qty * price)
        return abs(qty * price)

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
        step = float(spec.get("quantity_step") or 1.0)
        return _round_step(raw, step)

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
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        aid = str(asset_id).lower()
        side = str(side).lower()
        if aid in self.positions:
            return {"ok": False, "error": "position_already_open", "asset_id": aid}
        if not supports_side(aid, side):
            return {"ok": False, "error": "side_not_supported", "asset_id": aid, "side": side}
        spec = instrument_spec(aid)
        step = float(spec.get("quantity_step") or 1.0)
        qty = _round_step(float(quantity), step)
        price = float(price)
        if qty <= 0 or price <= 0:
            return {"ok": False, "error": "bad_qty_or_price", "asset_id": aid}
        fee = self._entry_fee(aid, qty, price, side)
        margin = self._required_margin(aid, side, qty, price)
        debit = margin + fee
        if self.usd + 1e-9 < debit:
            return {
                "ok": False,
                "error": "insufficient_usd",
                "need": debit,
                "have": self.usd,
                "asset_id": aid,
            }
        self.usd -= debit
        trade_id = uuid.uuid4().hex
        ts = opened_at or _now()
        pos = {
            "trade_id": trade_id,
            "asset_id": aid,
            "product_type": spec["product_type"],
            "side": side,
            "quantity": qty,
            "quantity_unit": spec["quantity_unit"],
            "entry_price": price,
            "entry_reference_price": float(reference_price or price),
            "entry_fee_usd": fee,
            "margin_reserved_usd": margin,
            "opened_at": ts,
            "mode": mode,
            "signal_key": signal_key,
            "initial_stop": float(stop_price) if stop_price else None,
            "current_stop": float(stop_price) if stop_price else None,
            "metadata": dict(metadata or {}),
        }
        self.positions[aid] = pos
        return {
            "ok": True,
            **pos,
            "price": price,
            "qty": qty,
            "fee": fee,
            "usd": self.usd,
        }

    def update_stop(self, asset_id: str, stop_price: float | None) -> None:
        pos = self.positions.get(str(asset_id).lower())
        if pos is not None:
            pos["current_stop"] = float(stop_price) if stop_price else None

    def close_position(
        self,
        asset_id: str,
        *,
        price: float,
        closed_at: str | None = None,
        exit_reason: str | None = None,
        reference_price: float | None = None,
    ) -> dict[str, Any]:
        aid = str(asset_id).lower()
        pos = self.positions.get(aid)
        if not pos:
            return {"ok": False, "error": "no_position", "asset_id": aid}
        price = float(price)
        if price <= 0:
            return {"ok": False, "error": "bad_price", "asset_id": aid}
        side = str(pos["side"])
        qty = float(pos["quantity"])
        gross = self.gross_pnl(aid, price)
        exit_fee = self._exit_fee(aid, qty, price, side)
        entry_fee = float(pos.get("entry_fee_usd") or 0.0)
        net = gross - entry_fee - exit_fee
        margin = float(pos.get("margin_reserved_usd") or 0.0)
        kind = str(pos["product_type"])

        if kind in {"crypto_spot", "equity"} and side == "long":
            # Cash long: reserved margin is the purchase notional. Return sale proceeds.
            self.usd += qty * price - exit_fee
        else:
            # Margin/short products: release margin and realize gross P/L.
            self.usd += margin + gross - exit_fee

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
            "exit_reference_price": float(reference_price or price),
            "exit_fee_usd": exit_fee,
            "fees_usd": entry_fee + exit_fee,
            "gross_pnl_usd": gross,
            "realized_pnl_usd": net,
            "exit_reason": exit_reason,
            "duration_seconds": duration,
            "status": "closed",
        }
        del self.positions[aid]
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
        for aid, pos in self.positions.items():
            mark = float(marks.get(aid, pos.get("entry_price") or 0.0) or 0.0)
            kind = str(pos["product_type"])
            side = str(pos["side"])
            qty = float(pos["quantity"])
            if kind in {"crypto_spot", "equity"} and side == "long":
                total += qty * mark
            else:
                total += float(pos.get("margin_reserved_usd") or 0.0)
                total += self.gross_pnl(aid, mark)
        return total

    def snapshot(self, marks: dict[str, float]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        reserved = 0.0
        gross_exposure = 0.0
        open_pnl = 0.0
        for aid, pos in self.positions.items():
            mark = float(marks.get(aid, pos.get("entry_price") or 0.0) or 0.0)
            pnl = self.open_pnl(aid, mark)
            notional = self.notional_usd(aid, mark)
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
            "usd": round(self.usd, 4),
            "cash": round(self.usd, 4),
            "equity": round(self.equity(marks), 4),
            "reserved_margin_usd": round(reserved, 4),
            "gross_exposure_usd": round(gross_exposure, 4),
            "open_pnl_usd": round(open_pnl, 4),
            "positions": rows,
            "holdings": rows,
            "model": "instrument_aware_paper_portfolio",
        }

    def payload(self) -> dict[str, Any]:
        return {
            "starting_usd": self.starting_usd,
            "usd": self.usd,
            "positions": self.positions,
            "closed_trades": self.closed_trades[-1000:],
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.starting_usd = float(data.get("starting_usd", self.starting_usd))
        self.usd = float(data.get("usd", self.usd))
        positions = data.get("positions") or {}
        self.positions = {
            str(k): dict(v)
            for k, v in positions.items()
            if isinstance(v, dict)
        }

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
                    "asset_id": aid,
                    "product_type": spec["product_type"],
                    "side": "long",
                    "quantity": qty,
                    "quantity_unit": spec["quantity_unit"],
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
