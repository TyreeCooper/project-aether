"""Read-only Kraken Spot account adapter.

This module performs authenticated account reads only. It does not expose an
order-placement method.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class KrakenValidationResult:
    valid: bool
    client_order_id: str
    description: str | None
    raw_result: dict


@dataclass(frozen=True)
class KrakenCredentialAssessment:
    valid_for_read_only_reconciliation: bool
    permissions: tuple[str, ...]
    missing_permissions: tuple[str, ...]
    prohibited_permissions: tuple[str, ...]


class KrakenSpotReadOnlyClient:
    base_url = "https://api.kraken.com"

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Kraken API key and secret are required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds
        self._last_nonce = 0

    def _next_nonce(self) -> str:
        candidate = time.time_ns() // 1_000_000
        self._last_nonce = max(candidate, self._last_nonce + 1)
        return str(self._last_nonce)

    @staticmethod
    def sign(
        *,
        path: str,
        payload: dict[str, str],
        api_secret: str,
    ) -> str:
        nonce = payload["nonce"]
        encoded = urlencode(payload)
        digest = hashlib.sha256((nonce + encoded).encode()).digest()
        message = path.encode() + digest
        secret = base64.b64decode(api_secret)
        signature = hmac.new(secret, message, hashlib.sha512).digest()
        return base64.b64encode(signature).decode()

    async def _private_post(
        self,
        path: str,
        payload: dict[str, str] | None = None,
    ) -> dict:
        body = dict(payload or {})
        body["nonce"] = self._next_nonce()
        signature = self.sign(
            path=path,
            payload=body,
            api_secret=self.api_secret,
        )
        headers = {
            "API-Key": self.api_key,
            "API-Sign": signature,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
            )
            response.raise_for_status()
            decoded = response.json()

        errors = decoded.get("error") or []
        if errors:
            raise RuntimeError("; ".join(str(item) for item in errors))
        return decoded.get("result") or {}

    async def get_api_key_info(self) -> dict:
        return await self._private_post("/0/private/GetApiKeyInfo")

    async def get_balances(self) -> dict[str, float]:
        raw = await self._private_post("/0/private/Balance")
        return {str(asset): float(value) for asset, value in raw.items()}

    @staticmethod
    def extract_btc_balance(balances: dict[str, float]) -> float:
        # Kraken has historically exposed BTC under XBT/XXBT identifiers.
        for key in ("BTC", "XBT", "XXBT"):
            if key in balances:
                return float(balances[key])
        return 0.0

    @staticmethod
    def assess_permissions(permissions: list[str] | tuple[str, ...]) -> KrakenCredentialAssessment:
        granted = tuple(sorted(set(permissions)))
        required = {"query-funds"}
        prohibited = {
            "withdraw-funds",
            "add-withdraw-address",
            "update-withdraw-address",
        }

        missing = tuple(sorted(required.difference(granted)))
        dangerous = tuple(sorted(prohibited.intersection(granted)))
        return KrakenCredentialAssessment(
            valid_for_read_only_reconciliation=not missing and not dangerous,
            permissions=granted,
            missing_permissions=missing,
            prohibited_permissions=dangerous,
        )



class KrakenSpotValidateOnlyClient(KrakenSpotReadOnlyClient):
    """Kraken Spot order validator that cannot submit a live order.

    Every request sent through validate_market_order hard-codes validate=true.
    There is deliberately no generic order-placement method.
    """

    async def validate_market_order(
        self,
        *,
        pair: str,
        side: str,
        volume: float,
        client_order_id: str,
    ) -> KrakenValidationResult:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if volume <= 0:
            raise ValueError("volume must be positive")
        if not pair:
            raise ValueError("pair is required")
        if not client_order_id:
            raise ValueError("client_order_id is required")

        result = await self._private_post(
            "/0/private/AddOrder",
            {
                "ordertype": "market",
                "type": side,
                "volume": format(volume, ".12g"),
                "pair": pair,
                "cl_ord_id": client_order_id,
                "validate": "true",
            },
        )

        descr = result.get("descr") or {}
        description = descr.get("order") if isinstance(descr, dict) else None

        return KrakenValidationResult(
            valid=True,
            client_order_id=client_order_id,
            description=str(description) if description is not None else None,
            raw_result=result,
        )
