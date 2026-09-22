"""Published venue fees for paper fills. Not invented spreads."""
from __future__ import annotations

import os
from typing import Any

from app.universe import BY_ID

KRAKEN_TIER1_TAKER = 0.008
TAKER_FEE = float(os.getenv("AETHER_TAKER_FEE_RATE", str(KRAKEN_TIER1_TAKER)))

BROKER_THEME = {
    "kraken": {
        "id": "kraken",
        "label": "Kraken",
        "logo": "/static/brokers/kraken.svg",
    },
    "interactive_brokers": {
        "id": "ibkr",
        "label": "Interactive Brokers",
        "logo": "/static/brokers/ibkr.svg",
    },
    "ibkr": {
        "id": "ibkr",
        "label": "Interactive Brokers",
        "logo": "/static/brokers/ibkr.svg",
    },
    "ninjatrader": {
        "id": "ninjatrader",
        "label": "NinjaTrader",
        "logo": "/static/brokers/ninjatrader.svg",
    },
    "tastyfx": {
        "id": "tastyfx",
        "label": "tastyfx",
        "logo": "/static/brokers/tastyfx.svg",
    },
    "binance": {
        "id": "binance",
        "label": "Binance.US watch",
        "logo": "/static/brokers/kraken.svg",
    },
}

NT_PER_SIDE = {
    "mes": 0.65,
    "mnq": 0.65,
    "mgc": 1.00,
    "mcl": 1.00,
    "us10y": 0.76,
}


def broker_of(asset_id: str) -> str:
    row = BY_ID.get(str(asset_id).lower()) or {}
    return str(row.get("broker") or row.get("venue") or "kraken").lower()


def theme(asset_id: str) -> dict[str, str]:
    return BROKER_THEME.get(broker_of(asset_id), BROKER_THEME["kraken"])


def kraken_taker() -> float:
    return TAKER_FEE


def fee_quote(
    asset_id: str,
    *,
    qty: float,
    price: float,
    side: str = "buy",
) -> dict[str, Any]:
    aid = str(asset_id).lower()
    broker = broker_of(aid)
    notional = abs(float(qty) * float(price))
    side = str(side).lower()

    if broker in {"kraken", "binance"} or aid in {"btc", "eth"}:
        rate = kraken_taker()
        fee = notional * rate
        return {
            "broker": "kraken",
            "model": "percent_taker",
            "rate": rate,
            "fee_usd": round(fee, 8),
            "source": "Kraken Spot Crypto Tier 1 taker 0.80% unless AETHER_TAKER_FEE_RATE set",
        }

    if broker in {"interactive_brokers", "ibkr"}:
        shares = abs(float(qty))
        commission = min(max(shares * 0.005, 1.0), max(notional * 0.01, 0.0))
        taf = shares * 0.000166 if side == "sell" else 0.0
        fee = commission + taf
        rate = fee / notional if notional else 0.0
        return {
            "broker": "interactive_brokers",
            "model": "ibkr_pro_fixed",
            "rate": rate,
            "fee_usd": round(fee, 8),
            "commission_usd": round(commission, 8),
            "taf_usd": round(taf, 8),
            "source": "IBKR Pro Fixed $0.005/share, $1 min, 1% cap + FINRA TAF on sells",
        }

    if broker == "ninjatrader":
        per_side = NT_PER_SIDE.get(aid, 0.91)
        contracts = max(abs(float(qty)), 1.0)
        fee = per_side * contracts
        rate = fee / notional if notional else 0.0
        return {
            "broker": "ninjatrader",
            "model": "per_contract_all_in",
            "rate": rate,
            "fee_usd": round(fee, 8),
            "per_side_usd": per_side,
            "source": "NinjaTrader Lifetime all-in per side as of 2026-07-01 commission table",
        }

    pip_frac = 0.00008 if aid == "eurusd" else 0.00010
    fee = notional * pip_frac
    return {
        "broker": broker,
        "model": "fx_spread_equivalent",
        "rate": pip_frac,
        "fee_usd": round(fee, 8),
        "source": "tastyfx typical retail pip cost until a live ticket exists",
    }


def fee_rate(asset_id: str, qty: float = 1.0, price: float = 1.0, side: str = "buy") -> float:
    q = fee_quote(asset_id, qty=qty, price=price, side=side)
    return float(q["rate"])
