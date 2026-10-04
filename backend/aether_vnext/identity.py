"""Canonical deterministic identities from the AETHER Master closures."""
from __future__ import annotations

from datetime import datetime
import hashlib


def route_id(asset_id: str, horizon: str, side: str) -> str:
    return (
        f"{str(asset_id).strip().lower()}:"
        f"{str(horizon).strip().lower()}:"
        f"{str(side).strip().lower()}"
    )


def position_key(asset_id: str, horizon: str) -> str:
    return f"{str(asset_id).strip().lower()}:{str(horizon).strip().lower()}"


def signal_key(
    *,
    setup_id: str,
    asset_id: str,
    horizon: str,
    side: str,
    trigger_bar_close_exchange_ts: datetime,
) -> str:
    raw = "|".join(
        (
            str(setup_id),
            str(asset_id).strip().lower(),
            str(horizon).strip().lower(),
            str(side).strip().lower(),
            trigger_bar_close_exchange_ts.isoformat(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def idempotency_key(
    *,
    ticket_id: str,
    side: str,
    qty: float,
    asset_id: str,
    horizon: str,
    signal_key_value: str,
) -> str:
    raw = "|".join(
        (
            str(ticket_id),
            str(side).strip().lower(),
            str(qty),
            str(asset_id).strip().lower(),
            str(horizon).strip().lower(),
            str(signal_key_value),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
