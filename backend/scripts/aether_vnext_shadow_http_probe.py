"""Read-only HTTP probe for deployed AETHER vNext shadow coexistence.

The probe validates only what HTTP can prove:
- the existing legacy health surface is still reachable;
- the vNext Floor is reachable through the shadow mount;
- the vNext Floor reports PAPER ONLY / LIVE BLOCKED;
- mutation methods are rejected on the vNext Floor route.

It deliberately does not claim process-level proof that no second trading runtime
exists. That remains a separate deployed-runtime observation in Phase-17 evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx


LEGACY_HEALTH_PATH = "/api/v1/health"
VNEXT_FLOOR_PATH = "/api/v1/vnext/floor"
MUTATION_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _endpoint(base_url: str, path: str) -> str:
    normalized = str(base_url).strip()
    if not normalized:
        raise ValueError("base_url is required")
    if not normalized.endswith("/"):
        normalized += "/"
    return urljoin(normalized, path.lstrip("/"))


def _bool_mode(payload: object, key: str) -> bool:
    if not isinstance(payload, dict):
        return False
    mode = payload.get("mode")
    if not isinstance(mode, dict):
        return False
    return mode.get(key) is True


async def probe_shadow_http(
    *,
    base_url: str,
    timeout_seconds: float = 12.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    """Run a non-mutating coexistence probe and return descriptive evidence."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    try:
        legacy = await client.get(_endpoint(base_url, LEGACY_HEALTH_PATH))
        floor = await client.get(_endpoint(base_url, VNEXT_FLOOR_PATH))

        mutation_status: dict[str, int] = {}
        for method in MUTATION_METHODS:
            response = await client.request(
                method,
                _endpoint(base_url, VNEXT_FLOOR_PATH),
            )
            mutation_status[method] = int(response.status_code)

        try:
            floor_payload: Any = floor.json()
        except Exception:
            floor_payload = None

        paper_only = _bool_mode(floor_payload, "paper_only")
        live_blocked = _bool_mode(floor_payload, "live_blocked")
        mutation_transport_absent = all(
            status == 405 for status in mutation_status.values()
        )

        return {
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_url": str(base_url).rstrip("/"),
            "legacy": {
                "path": LEGACY_HEALTH_PATH,
                "status_code": int(legacy.status_code),
                "available": 200 <= legacy.status_code < 300,
            },
            "vnext_floor": {
                "path": VNEXT_FLOOR_PATH,
                "status_code": int(floor.status_code),
                "available": floor.status_code == 200,
                "paper_only": paper_only,
                "live_blocked": live_blocked,
            },
            "mutation_methods": mutation_status,
            "mutation_transport_absent": mutation_transport_absent,
            "http_shadow_verified": bool(
                200 <= legacy.status_code < 300
                and floor.status_code == 200
                and paper_only
                and live_blocked
                and mutation_transport_absent
            ),
            "process_runtime_observation": {
                "verified": False,
                "reason": (
                    "HTTP probe cannot prove that no second trading runtime exists"
                ),
            },
            "authority": {
                "read_only": True,
                "may_switch_runtime": False,
                "may_start_runtime": False,
                "may_arm_runtime": False,
                "may_enable_live": False,
            },
        }
    finally:
        if owns_client:
            await client.aclose()


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    base_url: str,
    output: str | None,
    timeout_seconds: float,
) -> int:
    payload = await probe_shadow_http(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    _emit(payload, output)
    return 0 if payload["http_shadow_verified"] is True else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output")
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                base_url=args.base_url,
                output=args.output,
                timeout_seconds=args.timeout_seconds,
            )
        )
    )
