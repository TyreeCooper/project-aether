from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from aether_vnext.ninjatrader_contract_discovery import (
    CONTRACT_MATURITY_ITEMS_PATH,
    CONTRACT_SUGGEST_PATH,
    discover_contract_candidates,
    parse_contract_maturities,
    parse_contract_suggestions,
)


UTC = timezone.utc


def test_contract_suggestions_preserve_provider_ids_without_selection() -> None:
    rows = parse_contract_suggestions(
        [
            {
                "name": "MES Dec 26",
                "contractMaturityId": 202612,
                "timestamp": "2026-09-30T00:00:00Z",
                "id": 123456,
            },
            {
                "name": "MES Mar 27",
                "contractMaturityId": 202703,
                "timestamp": "2026-09-30T00:00:00Z",
                "id": 123457,
            },
        ]
    )
    assert [(row.name, row.contract_id) for row in rows] == [
        ("MES Dec 26", 123456),
        ("MES Mar 27", 123457),
    ]
    assert rows[0].provider_timestamp_utc == datetime(
        2026, 9, 30, 0, 0, tzinfo=UTC
    )


def test_maturity_parser_preserves_expiry_and_front_flag() -> None:
    rows = parse_contract_maturities(
        [
            {
                "productId": 150,
                "expirationMonth": 202612,
                "expirationDate": "2026-12-18T14:30:00Z",
                "isFront": True,
                "id": 202612,
                "firstIntentDate": "2026-12-01T00:00:00Z",
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0].maturity_id == 202612
    assert rows[0].is_front is True
    assert rows[0].expiration_utc == datetime(
        2026, 12, 18, 14, 30, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_discovery_joins_contracts_to_maturity_without_roll_choice() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith(CONTRACT_SUGGEST_PATH):
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "MES Dec 26",
                        "contractMaturityId": 202612,
                        "timestamp": "2026-09-30T00:00:00Z",
                        "id": 123456,
                    },
                    {
                        "name": "MES Mar 27",
                        "contractMaturityId": 202703,
                        "timestamp": "2026-09-30T00:00:00Z",
                        "id": 123457,
                    },
                ],
            )
        if request.url.path.endswith(CONTRACT_MATURITY_ITEMS_PATH):
            return httpx.Response(
                200,
                json=[
                    {
                        "productId": 150,
                        "expirationMonth": 202612,
                        "expirationDate": "2026-12-18T14:30:00Z",
                        "isFront": True,
                        "id": 202612,
                    },
                    {
                        "productId": 150,
                        "expirationMonth": 202703,
                        "expirationDate": "2027-03-19T14:30:00Z",
                        "isFront": False,
                        "id": 202703,
                    },
                ],
            )
        raise AssertionError(request.url)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://demo.tradovateapi.com/v1",
        headers={"Authorization": "Bearer caller-token"},
        transport=transport,
    ) as client:
        rows = await discover_contract_candidates(
            query_text="MES",
            limit=10,
            client=client,
        )

    assert len(rows) == 2
    assert rows[0].contract.contract_id == 123456
    assert rows[0].maturity.is_front is True
    assert rows[1].contract.contract_id == 123457
    assert rows[1].maturity.is_front is False
    assert calls[0][1] == {"t": "MES", "l": "10"}
    assert calls[1][1] == {"ids": "202612,202703"}


@pytest.mark.asyncio
async def test_discovery_uses_caller_auth_and_does_not_create_orders() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("auth", request.headers.get("Authorization"))
        if request.url.path.endswith(CONTRACT_SUGGEST_PATH):
            return httpx.Response(200, json=[])
        raise AssertionError("maturity endpoint should not be called")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://demo.tradovateapi.com/v1",
        headers={"Authorization": "Bearer caller-token"},
        transport=transport,
    ) as client:
        rows = await discover_contract_candidates(
            query_text="MES",
            limit=5,
            client=client,
        )
    assert rows == ()
    assert captured["auth"] == "Bearer caller-token"
