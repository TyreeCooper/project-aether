"""Four broker-local paper sleeves under one Firm book.

Capital is not fungible across venues. Consolidated equity is the sum of
marked sleeves. Execution spends only the target sleeve.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Seed weights from Operating Spec v4.2. Applied to whatever starting
# cash the Firm currently uses (300k in repo, 10k in the paper contract).
SLEEVE_WEIGHTS: dict[str, float] = {
    "kraken_paper": 0.40,
    "tastyfx_paper": 0.20,
    "ninja_paper": 0.20,
    "ibkr_paper": 0.20,
}

ASSET_SLEEVE: dict[str, str] = {
    "btc": "kraken_paper",
    "eth": "kraken_paper",
    "eurusd": "tastyfx_paper",
    "usdjpy": "tastyfx_paper",
    "mes": "ninja_paper",
    "mnq": "ninja_paper",
    "mgc": "ninja_paper",
    "mcl": "ninja_paper",
    "us10y": "ninja_paper",
    "nvda": "ibkr_paper",
    "tsla": "ibkr_paper",
    "pltr": "ibkr_paper",
}


def sleeve_for_asset(asset_id: str) -> str:
    aid = str(asset_id).lower().strip()
    if aid not in ASSET_SLEEVE:
        raise KeyError(f"no sleeve for asset: {aid}")
    return ASSET_SLEEVE[aid]


@dataclass
class SleeveLedger:
    broker_account_id: str
    cash_available_usd: float
    cash_reserved_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    fees_accrued_usd: float = 0.0

    @property
    def cash_total_usd(self) -> float:
        return float(self.cash_available_usd) + float(self.cash_reserved_usd)

    def snapshot(self) -> dict[str, Any]:
        return asdict(self) | {"cash_total_usd": self.cash_total_usd}


@dataclass
class SleeveBook:
    starting_usd: float
    ledgers: dict[str, SleeveLedger] = field(default_factory=dict)

    @classmethod
    def seed(cls, starting_usd: float) -> "SleeveBook":
        total = float(starting_usd)
        book = cls(starting_usd=total, ledgers={})
        allocated = 0.0
        items = list(SLEEVE_WEIGHTS.items())
        for i, (sid, weight) in enumerate(items):
            if i == len(items) - 1:
                cash = round(total - allocated, 8)
            else:
                cash = round(total * weight, 8)
                allocated += cash
            book.ledgers[sid] = SleeveLedger(
                broker_account_id=sid,
                cash_available_usd=cash,
            )
        return book

    def sleeve(self, sleeve_id: str) -> SleeveLedger:
        if sleeve_id not in self.ledgers:
            raise KeyError(f"unknown sleeve: {sleeve_id}")
        return self.ledgers[sleeve_id]

    def sleeve_for(self, asset_id: str) -> SleeveLedger:
        return self.sleeve(sleeve_for_asset(asset_id))

    @property
    def cash_available_usd(self) -> float:
        return sum(s.cash_available_usd for s in self.ledgers.values())

    @property
    def cash_reserved_usd(self) -> float:
        return sum(s.cash_reserved_usd for s in self.ledgers.values())

    def reserve(self, asset_id: str, amount: float, *, intent_id: str) -> dict[str, Any]:
        need = float(amount)
        if need <= 0:
            return {"ok": False, "error": "bad_reserve_amount"}
        sl = self.sleeve_for(asset_id)
        if sl.cash_available_usd + 1e-9 < need:
            return {
                "ok": False,
                "error": "insufficient_capital",
                "sleeve": sl.broker_account_id,
                "need": need,
                "have": sl.cash_available_usd,
                "intent_id": intent_id,
            }
        sl.cash_available_usd -= need
        sl.cash_reserved_usd += need
        return {
            "ok": True,
            "sleeve": sl.broker_account_id,
            "reserved_usd": need,
            "intent_id": intent_id,
            "cash_available_usd": sl.cash_available_usd,
        }

    def release(self, asset_id: str, amount: float) -> dict[str, Any]:
        sl = self.sleeve_for(asset_id)
        give = min(float(amount), sl.cash_reserved_usd)
        sl.cash_reserved_usd -= give
        sl.cash_available_usd += give
        return {"ok": True, "released_usd": give, "sleeve": sl.broker_account_id}

    def consume_reserve(self, asset_id: str, reserved: float, leftover: float = 0.0) -> None:
        """Fill used `reserved - leftover`. Leftover returns to available."""
        sl = self.sleeve_for(asset_id)
        reserved = min(float(reserved), sl.cash_reserved_usd)
        leftover = min(max(float(leftover), 0.0), reserved)
        sl.cash_reserved_usd -= reserved
        sl.cash_available_usd += leftover

    def credit(self, asset_id: str, amount: float) -> None:
        self.sleeve_for(asset_id).cash_available_usd += float(amount)

    def transfer(
        self,
        from_id: str,
        to_id: str,
        usd: float,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        amt = float(usd)
        if amt <= 0:
            return {"ok": False, "error": "bad_transfer_amount"}
        src = self.sleeve(from_id)
        dst = self.sleeve(to_id)
        if src.cash_available_usd + 1e-9 < amt:
            return {"ok": False, "error": "insufficient_capital", "sleeve": from_id}
        src.cash_available_usd -= amt
        dst.cash_available_usd += amt
        return {
            "ok": True,
            "from": from_id,
            "to": to_id,
            "usd": amt,
            "reason": reason,
            "actor": actor,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "starting_usd": self.starting_usd,
            "cash_available_usd": round(self.cash_available_usd, 6),
            "cash_reserved_usd": round(self.cash_reserved_usd, 6),
            "sleeves": {k: v.snapshot() for k, v in self.ledgers.items()},
        }

    def payload(self) -> dict[str, Any]:
        return {
            "starting_usd": self.starting_usd,
            "ledgers": {k: asdict(v) for k, v in self.ledgers.items()},
        }

    @classmethod
    def restore(cls, data: dict[str, Any], fallback_starting: float) -> "SleeveBook":
        starting = float(data.get("starting_usd") or fallback_starting)
        raw = data.get("ledgers")
        if not raw:
            return cls.seed(starting)
        book = cls(starting_usd=starting, ledgers={})
        for sid, row in raw.items():
            book.ledgers[str(sid)] = SleeveLedger(
                broker_account_id=str(row.get("broker_account_id") or sid),
                cash_available_usd=float(row.get("cash_available_usd") or 0.0),
                cash_reserved_usd=float(row.get("cash_reserved_usd") or 0.0),
                realized_pnl_usd=float(row.get("realized_pnl_usd") or 0.0),
                fees_accrued_usd=float(row.get("fees_accrued_usd") or 0.0),
            )
        return book
