"""Operator-local, read-only IBKR conid discovery for AETHER vNext.

Requires an authenticated IBKR Web API bearer token in the environment. The token is
never printed or written to the output. This tool only calls the stock discovery GET
endpoint and never selects or persists a conid.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from aether_vnext.ibkr_instrument_discovery import fetch_ibkr_stock_candidates


_ALLOWED_SYMBOLS = frozenset({"NVDA", "TSLA", "PLTR"})
_DEFAULT_BASE_URL = "https://localhost:5000/v1/api"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _validated_base_url(raw: str) -> str:
    value = str(raw).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("IBKR discovery base URL must be HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "IBKR discovery base URL must not contain credentials, query, or fragment"
        )
    return value


def _symbols(raw: str) -> tuple[str, ...]:
    values = tuple(
        value.strip().upper()
        for value in str(raw).split(",")
        if value.strip()
    )
    if not values:
        raise ValueError("at least one IBKR equity symbol is required")
    if len(values) != len(set(values)):
        raise ValueError("duplicate IBKR equity symbol")
    unsupported = tuple(value for value in values if value not in _ALLOWED_SYMBOLS)
    if unsupported:
        raise ValueError(
            "AETHER IBKR discovery supports only NVDA,TSLA,PLTR: "
            + ",".join(unsupported)
        )
    return values


def _serialize(rows, *, requested_symbols: tuple[str, ...]) -> dict[str, object]:
    return {
        "provider": "IBKR",
        "operation": "stock_conid_discovery",
        "binding_performed": False,
        "credential_values_present": False,
        "requested_symbols": list(requested_symbols),
        "candidate_count": len(rows),
        "candidates": [
            {
                "symbol": row.symbol,
                "company_name": row.company_name,
                "conid": row.conid,
                "exchange": row.exchange,
                "is_us": row.is_us,
            }
            for row in rows
        ],
    }


async def _main(*, symbols: tuple[str, ...], output: str | None) -> int:
    token = os.getenv(
        "AETHER_VNEXT_IBKR_DISCOVERY_BEARER_TOKEN",
        "",
    ).strip()
    if not token:
        raise RuntimeError(
            "AETHER_VNEXT_IBKR_DISCOVERY_BEARER_TOKEN is required"
        )

    base_url = _validated_base_url(
        os.getenv(
            "AETHER_VNEXT_IBKR_DISCOVERY_BASE_URL",
            _DEFAULT_BASE_URL,
        )
    )
    parsed = urlparse(base_url)
    allow_insecure = _truthy(
        os.getenv("AETHER_VNEXT_IBKR_ALLOW_INSECURE_LOCALHOST_TLS")
    )
    if allow_insecure and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "insecure TLS is permitted only for localhost/loopback IBKR discovery"
        )

    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=12.0,
        verify=not allow_insecure,
    ) as client:
        rows = await fetch_ibkr_stock_candidates(
            symbols=symbols,
            client=client,
        )

    rendered = json.dumps(
        _serialize(rows, requested_symbols=symbols),
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
    parser.add_argument("--symbols", default="NVDA,TSLA,PLTR")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                symbols=_symbols(args.symbols),
                output=args.output,
            )
        )
    )
