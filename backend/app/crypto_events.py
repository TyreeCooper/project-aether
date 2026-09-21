"""Crypto-native event calendar for Aether shadow intelligence.

CoinMarketCal is treated as a discovery/curation provider, not an execution
authority. Estimated dates are never converted into exact timestamps or blackout
windows. This module cannot create orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import httpx

COINMARKETCAL_EVENTS = "https://api.coinmarketcal.com/v2/events"


def _parse_dt(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_crypto_event(row: dict[str, Any]) -> dict[str, Any] | None:
    event_id = str(row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    when = _parse_dt(row.get("date"))
    if not title or when is None:
        return None

    estimated = bool(row.get("isEstimated"))
    coins: list[dict[str, str]] = []
    for coin in row.get("coins") or []:
        if not isinstance(coin, dict):
            continue
        symbol = str(coin.get("symbol") or "").strip().lower()
        if not symbol:
            continue
        coins.append(
            {
                "symbol": symbol,
                "slug": str(coin.get("slug") or "").strip(),
                "name": str(coin.get("name") or symbol.upper()).strip(),
            }
        )

    categories = [
        str(value).strip()
        for value in (row.get("categories") or [])
        if str(value).strip()
    ]
    proof_url = str(row.get("sourceUrl") or "").strip() or None
    verified_at = _parse_dt(row.get("lastVerifiedAt"))
    date_end = _parse_dt(row.get("dateEnd"))

    return {
        "id": event_id or None,
        "title": title,
        "description": str(row.get("description") or "").strip() or None,
        "provider": "CoinMarketCal",
        "provider_event_id": event_id or None,
        "coins": coins,
        "categories": categories,
        "impact": _float_or_none(row.get("impact")),
        "impact_summary": str(row.get("impactSummary") or "").strip() or None,
        "is_estimated": estimated,
        "date_type": str(row.get("dateType") or "").strip() or None,
        "displayed_date": str(row.get("displayedDate") or "").strip()
        or when.date().isoformat(),
        # Exact timestamp is intentionally withheld for estimated/window dates.
        "scheduled_at": None if estimated else when.astimezone(timezone.utc).isoformat(),
        "date_anchor": when.astimezone(timezone.utc).isoformat(),
        "date_end": (
            date_end.astimezone(timezone.utc).isoformat()
            if date_end is not None
            else None
        ),
        "source_url": proof_url,
        "provider_verified_at": (
            verified_at.astimezone(timezone.utc).isoformat()
            if verified_at is not None
            else None
        ),
        "proof_linked": bool(proof_url),
        "state": "observe",
        "trade_influence_enabled": False,
        "risk_window_enforced": False,
        "note": (
            "Estimated calendar window; no exact Aether blackout time may be inferred."
            if estimated
            else "Exact provider timestamp is visible for observation only; risk enforcement is not enabled."
        ),
    }


def _api_key() -> str:
    return os.getenv("COINMARKETCAL_API_KEY", "").strip()


async def fetch_crypto_calendar(
    tracked_symbols: list[str] | tuple[str, ...] | set[str] | None = None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    key = _api_key()
    if not key:
        return {
            "provider": "CoinMarketCal",
            "configured": False,
            "connected": False,
            "status": "unconfigured",
            "events": [],
            "note": "COINMARKETCAL_API_KEY is not configured.",
        }

    params = {
        "limit": max(1, min(int(limit), 100)),
        "sortBy": "date_asc",
    }
    headers = {
        "x-api-key": key,
        "Accept": "application/json",
        "User-Agent": "Project-Aether/1.0 crypto-event-shadow",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(COINMARKETCAL_EVENTS, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "provider": "CoinMarketCal",
            "configured": True,
            "connected": False,
            "status": "degraded",
            "events": [],
            "error": type(exc).__name__,
            "note": "Crypto-event provider unavailable; missing data is not interpreted as no event risk.",
        }

    wanted = {
        str(symbol).strip().lower()
        for symbol in (tracked_symbols or [])
        if str(symbol).strip()
    }
    rows = payload.get("data") if isinstance(payload, dict) else []
    events: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        event = normalize_crypto_event(row)
        if event is None:
            continue
        if wanted:
            event_symbols = {coin["symbol"] for coin in event["coins"]}
            if event_symbols.isdisjoint(wanted):
                continue
        events.append(event)

    events.sort(
        key=lambda row: str(row.get("date_anchor") or row.get("scheduled_at") or "")
    )
    return {
        "provider": "CoinMarketCal",
        "configured": True,
        "connected": True,
        "status": "connected",
        "events": events,
        "count": len(events),
        "note": "Crypto events are shadow intelligence and cannot directly create orders.",
    }
