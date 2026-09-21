"""Kraken-style volume and cost floors. Loaded from AssetPairs later."""
from __future__ import annotations

COST_MIN_USD = 0.5

# Base volume mins from public Kraken docs / conservative floors.
VOLUME_MIN = {
    "btc": 0.0001,
    "eth": 0.002,
    "sol": 0.05,
    "xrp": 5.0,
    "bnb": 0.02,
    "ada": 15.0,
    "link": 0.2,
    "ton": 1.0,
    "avax": 0.1,
    "sui": 1.0,
}


def volume_min(asset: str) -> float:
    return float(VOLUME_MIN.get(asset, 0.01))


def size_ok(asset: str, qty: float, price: float) -> tuple[bool, str]:
    qty = float(qty)
    price = float(price)
    if qty + 1e-12 < volume_min(asset):
        return False, "volume_min"
    if qty * price + 1e-12 < COST_MIN_USD:
        return False, "cost_min"
    return True, "ok"
