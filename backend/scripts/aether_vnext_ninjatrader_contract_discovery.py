"""Operator-local, read-only NinjaTrader/Tradovate contract discovery.

The tool is deliberately pinned to the documented DEMO REST host, accepts only
AETHER's futures assets, performs GET-only contract/maturity discovery, and never
selects or persists the current/next contract.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from aether_vnext.ninjatrader_contract_discovery import (
    discover_contract_candidates,
)
from aether_vnext.registry import registry_row


_DEMO_BASE_URL = "https://demo.tradovateapi.com/v1"
_ALLOWED_ASSETS = frozenset({"mes", "mnq", "mgc", "mcl", "us10y"})


def _assets(raw: str) -> tuple[str, ...]:
    values = tuple(
        value.strip().lower()
        for value in str(raw).split(",")
        if value.strip()
    )
    if not values:
        raise ValueError("at least one NinjaTrader futures asset is required")
    if len(values) != len(set(values)):
        raise ValueError("duplicate NinjaTrader futures asset")
    unsupported = tuple(value for value in values if value not in _ALLOWED_ASSETS)
    if unsupported:
        raise ValueError(
            "AETHER NinjaTrader discovery supports only mes,mnq,mgc,mcl,us10y: "
            + ",".join(unsupported)
        )
    return values


def _demo_base_url(raw: str) -> str:
    value = str(raw).strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "demo.tradovateapi.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "NinjaTrader discovery is restricted to "
            "https://demo.tradovateapi.com/v1"
        )
    if parsed.path.rstrip("/") != "/v1":
        raise ValueError(
            "NinjaTrader discovery is restricted to the DEMO /v1 API"
        )
    return value


def _serialize(rows_by_asset: dict[str, tuple]) -> dict[str, object]:
    return {
        "provider": "NinjaTrader",
        "transport": "Tradovate_DEMO_REST",
        "operation": "futures_contract_discovery",
        "binding_performed": False,
        "credential_values_present": False,
        "assets": [
            {
                "asset_id": asset_id,
                "query_symbol": registry_row(asset_id).canonical_symbol,
                "candidate_count": len(rows_by_asset[asset_id]),
                "candidates": [
                    {
                        "contract_name": row.contract.name,
                        "contract_id": row.contract.contract_id,
                        "contract_maturity_id": (
                            row.contract.contract_maturity_id
                        ),
                        "provider_timestamp_utc": (
                            None
                            if row.contract.provider_timestamp_utc is None
                            else row.contract.provider_timestamp_utc.isoformat()
                        ),
                        "product_id": row.maturity.product_id,
                        "expiration_month": row.maturity.expiration_month,
                        "expiration_utc": row.maturity.expiration_utc.isoformat(),
                        "is_front": row.maturity.is_front,
                        "first_intent_utc": (
                            None
                            if row.maturity.first_intent_utc is None
                            else row.maturity.first_intent_utc.isoformat()
                        ),
                    }
                    for row in rows_by_asset[asset_id]
                ],
            }
            for asset_id in sorted(rows_by_asset)
        ],
    }


async def _main(
    *,
    assets: tuple[str, ...],
    limit: int,
    output: str | None,
) -> int:
    if isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    token = os.getenv(
        "AETHER_VNEXT_NINJATRADER_DISCOVERY_TOKEN",
        "",
    ).strip()
    if not token:
        raise RuntimeError(
            "AETHER_VNEXT_NINJATRADER_DISCOVERY_TOKEN is required"
        )

    base_url = _demo_base_url(
        os.getenv(
            "AETHER_VNEXT_NINJATRADER_DISCOVERY_BASE_URL",
            _DEMO_BASE_URL,
        )
    )

    rows_by_asset: dict[str, tuple] = {}
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=12.0,
    ) as client:
        for asset_id in assets:
            rows_by_asset[asset_id] = await discover_contract_candidates(
                query_text=registry_row(asset_id).canonical_symbol,
                limit=limit,
                client=client,
            )

    rendered = json.dumps(
        _serialize(rows_by_asset),
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        default="mes,mnq,mgc,mcl,us10y",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                assets=_assets(args.assets),
                limit=args.limit,
                output=args.output,
            )
        )
    )
