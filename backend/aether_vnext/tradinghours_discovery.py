"""Read-only TradingHours market discovery for AETHER vNext.

This helper enumerates markets the authenticated TradingHours account is allowed to
access. It never selects a FinID for AETHER automatically and never writes runtime
bindings. The returned candidates are evidence for later human/repository review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from aether_vnext.tradinghours_calendar import TRADINGHOURS_API_BASE


TRADINGHOURS_MARKETS_ENDPOINT = f"{TRADINGHOURS_API_BASE}/markets"


@dataclass(frozen=True, slots=True)
class TradingHoursMarketCandidate:
    fin_id: str
    exchange: str
    market: str
    products: str | None
    mic: str | None
    asset_type: str | None
    group: str | None

    def __post_init__(self) -> None:
        if not self.fin_id.strip():
            raise ValueError("TradingHours fin_id is required")
        if not self.exchange.strip():
            raise ValueError("TradingHours exchange is required")
        if not self.market.strip():
            raise ValueError("TradingHours market is required")


def parse_tradinghours_markets(payload: object) -> tuple[TradingHoursMarketCandidate, ...]:
    if not isinstance(payload, dict):
        raise ValueError("TradingHours markets payload must be an object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("TradingHours markets payload missing data list")

    out: list[TradingHoursMarketCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fin_id = str(row.get("fin_id") or "").strip()
        exchange = str(row.get("exchange") or "").strip()
        market = str(row.get("market") or "").strip()
        if not fin_id or not exchange or not market:
            continue
        out.append(
            TradingHoursMarketCandidate(
                fin_id=fin_id,
                exchange=exchange,
                market=market,
                products=(
                    None
                    if row.get("products") in (None, "")
                    else str(row.get("products")).strip()
                ),
                mic=(
                    None
                    if row.get("mic") in (None, "")
                    else str(row.get("mic")).strip()
                ),
                asset_type=(
                    None
                    if row.get("asset_type") in (None, "")
                    else str(row.get("asset_type")).strip()
                ),
                group=(
                    None
                    if row.get("group") in (None, "")
                    else str(row.get("group")).strip()
                ),
            )
        )
    return tuple(out)


async def fetch_allowed_tradinghours_markets(
    *,
    api_token: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[TradingHoursMarketCandidate, ...]:
    """Enumerate only markets available to the authenticated subscription."""
    token = str(api_token).strip()
    if not token:
        raise ValueError("TradingHours API token is required")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    try:
        response = await http.get(
            TRADINGHOURS_MARKETS_ENDPOINT,
            params={"group": "allowed"},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        response.raise_for_status()
        return parse_tradinghours_markets(response.json())
    finally:
        if owns_client:
            await http.aclose()
