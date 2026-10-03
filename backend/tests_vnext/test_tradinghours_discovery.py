from __future__ import annotations

import httpx
import pytest

from aether_vnext.tradinghours_discovery import (
    TRADINGHOURS_MARKETS_ENDPOINT,
    fetch_allowed_tradinghours_markets,
    parse_tradinghours_markets,
)


def test_parse_market_candidates_preserves_provider_identity() -> None:
    rows = parse_tradinghours_markets(
        {
            "data": [
                {
                    "fin_id": "US.NYSE",
                    "exchange": "New York Stock Exchange",
                    "market": "Canonical",
                    "products": None,
                    "mic": "XNYS",
                    "asset_type": "Securities",
                    "group": "Core",
                },
                {"fin_id": "", "exchange": "bad", "market": "bad"},
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0].fin_id == "US.NYSE"
    assert rows[0].mic == "XNYS"


@pytest.mark.asyncio
async def test_fetch_uses_allowed_scope_and_does_not_bind_anything() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "fin_id": "US.CME",
                        "exchange": "CME",
                        "market": "Example",
                        "products": "Index futures",
                        "mic": "XCME",
                        "asset_type": "Futures",
                        "group": "Allowed",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        rows = await fetch_allowed_tradinghours_markets(
            api_token="token",
            client=client,
        )

    assert rows[0].fin_id == "US.CME"
    assert str(captured["url"]).startswith(TRADINGHOURS_MARKETS_ENDPOINT)
    assert "group=allowed" in str(captured["url"])
    assert captured["auth"] == "Bearer token"


@pytest.mark.asyncio
async def test_empty_token_fails_before_network() -> None:
    with pytest.raises(ValueError, match="API token is required"):
        await fetch_allowed_tradinghours_markets(api_token="")
