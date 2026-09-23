"""Canonical paper-trading specifications for Aether's 12 official books.

These specifications describe instrument math, not live broker permissions.
Dynamic live margin/borrow/contract selection belongs to the broker adapters.
"""
from __future__ import annotations

from typing import Any


INSTRUMENTS: dict[str, dict[str, Any]] = {
    "btc": {
        "product_type": "crypto_spot",
        "quantity_unit": "BTC",
        "supports_long": True,
        "supports_short": False,
        "cash_product": True,
        "price_multiplier": 1.0,
        "quantity_step": 0.00000001,
    },
    "eth": {
        "product_type": "crypto_spot",
        "quantity_unit": "ETH",
        "supports_long": True,
        "supports_short": False,
        "cash_product": True,
        "price_multiplier": 1.0,
        "quantity_step": 0.00000001,
    },
    "nvda": {
        "product_type": "equity",
        "quantity_unit": "shares",
        "supports_long": True,
        "supports_short": True,
        "cash_product": True,
        "price_multiplier": 1.0,
        "quantity_step": 1.0,
        "paper_short_margin_rate": 0.50,
    },
    "tsla": {
        "product_type": "equity",
        "quantity_unit": "shares",
        "supports_long": True,
        "supports_short": True,
        "cash_product": True,
        "price_multiplier": 1.0,
        "quantity_step": 1.0,
        "paper_short_margin_rate": 0.50,
    },
    "pltr": {
        "product_type": "equity",
        "quantity_unit": "shares",
        "supports_long": True,
        "supports_short": True,
        "cash_product": True,
        "price_multiplier": 1.0,
        "quantity_step": 1.0,
        "paper_short_margin_rate": 0.50,
    },
    "eurusd": {
        "product_type": "fx",
        "quantity_unit": "EUR units",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "base_currency": "EUR",
        "quote_currency": "USD",
        "pip_size": 0.0001,
        "quantity_step": 100.0,
        "standard_lot_units": 100_000.0,
        "max_standard_lots": 1.0,
        "max_quantity": 100_000.0,
        "paper_margin_rate": 0.05,
    },
    "usdjpy": {
        "product_type": "fx",
        "quantity_unit": "USD units",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "base_currency": "USD",
        "quote_currency": "JPY",
        "pip_size": 0.01,
        "quantity_step": 100.0,
        "standard_lot_units": 100_000.0,
        "max_standard_lots": 1.0,
        "max_quantity": 100_000.0,
        "paper_margin_rate": 0.05,
    },
    "mes": {
        "product_type": "future",
        "quantity_unit": "contracts",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "contract_code": "MES",
        "point_value_usd": 5.0,
        "tick_size": 0.25,
        "tick_value_usd": 1.25,
        "quantity_step": 1.0,
        "max_quantity": 1.0,
        "paper_margin_rate": 0.10,
    },
    "mnq": {
        "product_type": "future",
        "quantity_unit": "contracts",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "contract_code": "MNQ",
        "point_value_usd": 2.0,
        "tick_size": 0.25,
        "tick_value_usd": 0.50,
        "quantity_step": 1.0,
        "max_quantity": 1.0,
        "paper_margin_rate": 0.10,
    },
    "mgc": {
        "product_type": "future",
        "quantity_unit": "contracts",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "contract_code": "MGC",
        "point_value_usd": 10.0,
        "tick_size": 0.10,
        "tick_value_usd": 1.0,
        "quantity_step": 1.0,
        "max_quantity": 1.0,
        "paper_margin_rate": 0.10,
    },
    "mcl": {
        "product_type": "future",
        "quantity_unit": "contracts",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "contract_code": "MCL",
        "point_value_usd": 100.0,
        "tick_size": 0.01,
        "tick_value_usd": 1.0,
        "quantity_step": 1.0,
        "max_quantity": 1.0,
        "paper_margin_rate": 0.10,
    },
    "us10y": {
        "product_type": "future",
        "quantity_unit": "contracts",
        "supports_long": True,
        "supports_short": True,
        "cash_product": False,
        "contract_code": "10Y",
        "point_value_usd": 1000.0,
        "tick_size": 0.001,
        "tick_value_usd": 1.0,
        "quantity_step": 1.0,
        "max_quantity": 1.0,
        "paper_margin_rate": 0.10,
    },
}


def instrument_spec(asset_id: str) -> dict[str, Any]:
    aid = str(asset_id).lower()
    if aid not in INSTRUMENTS:
        raise KeyError(f"unknown instrument: {aid}")
    return dict(INSTRUMENTS[aid])


def supports_side(asset_id: str, side: str) -> bool:
    spec = instrument_spec(asset_id)
    normalized = str(side).lower()
    if normalized == "long":
        return bool(spec["supports_long"])
    if normalized == "short":
        return bool(spec["supports_short"])
    return False

def quantity_metadata(
    asset_id: str,
    quantity: float,
) -> dict[str, Any]:
    spec = instrument_spec(asset_id)
    qty = abs(float(quantity))
    kind = str(spec["product_type"])
    out: dict[str, Any] = {
        "quantity_unit": spec["quantity_unit"],
        "max_quantity": spec.get("max_quantity"),
    }
    if kind == "fx":
        lot_units = float(
            spec.get("standard_lot_units") or 100_000.0
        )
        out.update(
            {
                "base_units": qty,
                "standard_lot_units": lot_units,
                "standard_lots": round(qty / lot_units, 8),
                "max_standard_lots": spec.get(
                    "max_standard_lots"
                ),
            }
        )
    elif kind == "future":
        out["contracts"] = qty
    elif kind == "equity":
        out["shares"] = qty
    elif kind == "crypto_spot":
        out["coin_quantity"] = qty
    return out
