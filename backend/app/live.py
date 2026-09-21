"""Live rail. Wired for keys. Orders stay blocked until AETHER_LIVE=1."""
from __future__ import annotations

import os
from typing import Any


def status() -> dict[str, Any]:
    key = os.getenv("KRAKEN_API_KEY", "").strip()
    secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    armed = os.getenv("AETHER_LIVE", "").strip() in {"1", "true", "TRUE", "yes"}
    keys_present = bool(key and secret)
    return {
        "keys_present": keys_present,
        "live_flag": armed,
        "live_ready": keys_present,
        "live_armed": False,
        "orders_enabled": False,
        "reason": (
            "Keys present. Live flag off. Paper only."
            if keys_present and not armed
            else "Set KRAKEN_API_KEY / KRAKEN_API_SECRET in Azure. Keep AETHER_LIVE=0 until paper holds."
            if not keys_present
            else "AETHER_LIVE is set but live orders stay blocked until a signed client ships."
        ),
    }


async def place_order(
    *,
    pair: str = "XBTUSD",
    side: str = "buy",
    volume: float = 0.0,
    **_kwargs: Any,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "live_orders_blocked",
        "pair": pair,
        "side": side,
        "volume": volume,
        **status(),
    }
