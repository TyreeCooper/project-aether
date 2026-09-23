"""One spot cash account. USD plus coin balances, like Kraken funding."""
from __future__ import annotations

from typing import Any

from app.fees import TAKER_FEE

STARTING_USD = 300_000.0


class SpotWallet:
    def __init__(self, usd: float = STARTING_USD) -> None:
        self.usd = float(usd)
        self.units: dict[str, float] = {}
        self.avg: dict[str, float] = {}

    def qty(self, asset: str) -> float:
        return float(self.units.get(asset, 0.0) or 0.0)

    def avg_entry(self, asset: str) -> float:
        return float(self.avg.get(asset, 0.0) or 0.0)

    def equity(self, marks: dict[str, float]) -> float:
        total = self.usd
        for asset, qty in self.units.items():
            total += qty * float(marks.get(asset, 0.0) or 0.0)
        return total

    def can_buy(self, notional: float) -> bool:
        return notional > 0 and self.usd >= notional

    def buy(self, asset: str, qty: float, price: float, fee_rate: float = TAKER_FEE) -> dict[str, Any]:
        qty = float(qty)
        price = float(price)
        if qty <= 0 or price <= 0:
            return {"ok": False, "error": "bad_qty_or_price"}
        gross = qty * price
        fee = gross * float(fee_rate)
        cost = gross + fee
        if self.usd + 1e-9 < cost:
            return {"ok": False, "error": "insufficient_usd", "need": cost, "have": self.usd}
        prior = self.qty(asset)
        prior_avg = self.avg_entry(asset)
        self.usd -= cost
        new_qty = prior + qty
        self.units[asset] = new_qty
        self.avg[asset] = (
            (prior_avg * prior + price * qty + fee) / new_qty if new_qty else 0.0
        )
        return {"ok": True, "qty": qty, "price": price, "fee": fee, "usd": self.usd}

    def sell(self, asset: str, qty: float, price: float, fee_rate: float = TAKER_FEE) -> dict[str, Any]:
        qty = min(float(qty), self.qty(asset))
        price = float(price)
        if qty <= 0 or price <= 0:
            return {"ok": False, "error": "bad_qty_or_price"}
        gross = qty * price
        fee = gross * float(fee_rate)
        prior = self.qty(asset)
        avg = self.avg_entry(asset)
        pnl = (price - avg) * qty - fee
        self.units[asset] = prior - qty
        if self.units[asset] <= 1e-12:
            self.units[asset] = 0.0
            self.avg[asset] = 0.0
        self.usd += gross - fee
        return {"ok": True, "qty": qty, "price": price, "fee": fee, "pnl": pnl, "usd": self.usd}

    def snapshot(self, marks: dict[str, float]) -> dict[str, Any]:
        holdings = []
        for asset, qty in self.units.items():
            if qty <= 0:
                continue
            mark = float(marks.get(asset, 0.0) or 0.0)
            holdings.append(
                {
                    "asset": asset,
                    "qty": qty,
                    "avg": self.avg_entry(asset),
                    "mark": mark,
                    "value": qty * mark,
                    "open_pnl": (mark - self.avg_entry(asset)) * qty if mark else 0.0,
                }
            )
        return {
            "usd": round(self.usd, 4),
            "equity": round(self.equity(marks), 4),
            "holdings": holdings,
            "model": "kraken_spot_one_account",
        }

    def payload(self) -> dict[str, Any]:
        return {"usd": self.usd, "units": dict(self.units), "avg": dict(self.avg)}

    def restore(self, data: dict[str, Any]) -> None:
        self.usd = float(data.get("usd", self.usd))
        self.units = {str(k): float(v) for k, v in (data.get("units") or {}).items()}
        self.avg = {str(k): float(v) for k, v in (data.get("avg") or {}).items()}
