from __future__ import annotations

import httpx
import pytest

from aether_vnext.ibkr_instrument_discovery import (
    IBKR_STOCK_DISCOVERY_PATH,
    fetch_ibkr_stock_candidates,
    parse_ibkr_stock_candidates,
)


def _payload() -> dict:
    return {
        "NVDA": [
            {
                "name": "NVIDIA CORP",
                "assetClass": "STK",
                "contracts": [
                    {
                        "conid": 4815747,
                        "exchange": "NASDAQ",
                        "isUS": True,
                    },
                    {
                        "conid": 999,
                        "exchange": "MEXI",
                        "isUS": False,
                    },
                ],
            }
        ],
        "TSLA": [
            {
                "name": "TESLA INC",
                "assetClass": "STK",
                "contracts": [
                    {
                        "conid": 76792991,
                        "exchange": "NASDAQ",
                        "isUS": True,
                    }
                ],
            }
        ],
    }


def test_parser_preserves_all_provider_candidates_without_selecting_one() -> None:
    rows = parse_ibkr_stock_candidates(
        _payload(),
        requested_symbols=("NVDA", "TSLA", "PLTR"),
    )
    assert [(row.symbol, row.conid, row.exchange) for row in rows] == [
        ("NVDA", 4815747, "NASDAQ"),
        ("NVDA", 999, "MEXI"),
        ("TSLA", 76792991, "NASDAQ"),
    ]


def test_parser_rejects_empty_or_duplicate_request_identity() -> None:
    with pytest.raises(ValueError, match="at least one"):
        parse_ibkr_stock_candidates({}, requested_symbols=())
    with pytest.raises(ValueError, match="duplicate"):
        parse_ibkr_stock_candidates(
            {},
            requested_symbols=("NVDA", "nvda"),
        )


@pytest.mark.asyncio
async def test_fetch_uses_stock_discovery_endpoint_and_caller_auth() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["symbols"] = request.url.params.get("symbols")
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://localhost:5000/v1/api",
        headers={"Authorization": "Bearer caller-session"},
        transport=transport,
    ) as client:
        rows = await fetch_ibkr_stock_candidates(
            symbols=("NVDA", "TSLA", "PLTR"),
            client=client,
        )

    assert captured["path"].endswith(IBKR_STOCK_DISCOVERY_PATH)
    assert captured["symbols"] == "NVDA,TSLA,PLTR"
    assert captured["auth"] == "Bearer caller-session"
    assert any(row.symbol == "NVDA" for row in rows)


@pytest.mark.asyncio
async def test_fetch_does_not_invent_authentication() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") is None
        assert request.headers.get("Cookie") is None
        return httpx.Response(200, json={"NVDA": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://localhost:5000/v1/api",
        transport=transport,
    ) as client:
        rows = await fetch_ibkr_stock_candidates(
            symbols=("NVDA",),
            client=client,
        )
    assert rows == ()
