"""Read-only NinjaTrader/Tradovate futures contract discovery.

The provider's Contract Library exposes:
- GET /contract/suggest?t=<text>&l=<limit> -> Contract candidates
- GET /contractMaturity/items?ids=<ids> -> maturity/expiration facts

This module preserves those provider facts as candidates. It never chooses the
current or next AETHER contract automatically, never applies a roll decision, and
never writes runtime bindings. Authentication is supplied by the caller's already
authenticated httpx client.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

import httpx


CONTRACT_SUGGEST_PATH = "/contract/suggest"
CONTRACT_MATURITY_ITEMS_PATH = "/contractMaturity/items"


def _aware_datetime(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


@dataclass(frozen=True, slots=True)
class TradovateContractCandidate:
    name: str
    contract_maturity_id: int
    contract_id: int
    provider_timestamp_utc: datetime | None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("contract name is required")
        if (
            isinstance(self.contract_maturity_id, bool)
            or int(self.contract_maturity_id) <= 0
        ):
            raise ValueError("contract_maturity_id must be a positive integer")
        if isinstance(self.contract_id, bool) or int(self.contract_id) <= 0:
            raise ValueError("contract_id must be a positive integer")
        if (
            self.provider_timestamp_utc is not None
            and self.provider_timestamp_utc.tzinfo is None
        ):
            raise ValueError("provider_timestamp_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TradovateContractMaturity:
    maturity_id: int
    product_id: int
    expiration_month: int
    expiration_utc: datetime
    is_front: bool
    first_intent_utc: datetime | None

    def __post_init__(self) -> None:
        for name in ("maturity_id", "product_id", "expiration_month"):
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.expiration_utc.tzinfo is None:
            raise ValueError("expiration_utc must be timezone-aware")
        if (
            self.first_intent_utc is not None
            and self.first_intent_utc.tzinfo is None
        ):
            raise ValueError("first_intent_utc must be timezone-aware")
        if not isinstance(self.is_front, bool):
            raise ValueError("is_front must be boolean")


@dataclass(frozen=True, slots=True)
class TradovateResolvedContractCandidate:
    contract: TradovateContractCandidate
    maturity: TradovateContractMaturity


def parse_contract_suggestions(
    payload: object,
) -> tuple[TradovateContractCandidate, ...]:
    if not isinstance(payload, list):
        raise ValueError("contract suggest payload must be a list")

    out: list[TradovateContractCandidate] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        try:
            maturity_id = int(row.get("contractMaturityId"))
            contract_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if not name or maturity_id <= 0 or contract_id <= 0:
            continue
        timestamp_raw = row.get("timestamp")
        timestamp = (
            None
            if timestamp_raw in (None, "")
            else _aware_datetime(timestamp_raw, field="timestamp")
        )
        out.append(
            TradovateContractCandidate(
                name=name,
                contract_maturity_id=maturity_id,
                contract_id=contract_id,
                provider_timestamp_utc=timestamp,
            )
        )
    return tuple(out)


def parse_contract_maturities(
    payload: object,
) -> tuple[TradovateContractMaturity, ...]:
    if not isinstance(payload, list):
        raise ValueError("contract maturity payload must be a list")

    out: list[TradovateContractMaturity] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        try:
            maturity_id = int(row.get("id"))
            product_id = int(row.get("productId"))
            expiration_month = int(row.get("expirationMonth"))
        except (TypeError, ValueError):
            continue
        is_front = row.get("isFront")
        if (
            maturity_id <= 0
            or product_id <= 0
            or expiration_month <= 0
            or not isinstance(is_front, bool)
        ):
            continue
        expiration = _aware_datetime(
            row.get("expirationDate"),
            field="expirationDate",
        )
        first_intent_raw = row.get("firstIntentDate")
        first_intent = (
            None
            if first_intent_raw in (None, "")
            else _aware_datetime(
                first_intent_raw,
                field="firstIntentDate",
            )
        )
        out.append(
            TradovateContractMaturity(
                maturity_id=maturity_id,
                product_id=product_id,
                expiration_month=expiration_month,
                expiration_utc=expiration,
                is_front=is_front,
                first_intent_utc=first_intent,
            )
        )
    return tuple(out)


async def discover_contract_candidates(
    *,
    query_text: str,
    limit: int,
    client: httpx.AsyncClient,
) -> tuple[TradovateResolvedContractCandidate, ...]:
    """Return provider candidates joined to provider maturity facts."""
    query = str(query_text).strip()
    if not query:
        raise ValueError("query_text is required")
    if isinstance(limit, bool) or int(limit) <= 0:
        raise ValueError("limit must be a positive integer")

    suggest_response = await client.get(
        CONTRACT_SUGGEST_PATH,
        params={"t": query, "l": int(limit)},
    )
    suggest_response.raise_for_status()
    contracts = parse_contract_suggestions(suggest_response.json())
    if not contracts:
        return ()

    maturity_ids = tuple(
        dict.fromkeys(row.contract_maturity_id for row in contracts)
    )
    maturity_response = await client.get(
        CONTRACT_MATURITY_ITEMS_PATH,
        params={"ids": ",".join(str(value) for value in maturity_ids)},
    )
    maturity_response.raise_for_status()
    maturities = {
        row.maturity_id: row
        for row in parse_contract_maturities(maturity_response.json())
    }

    return tuple(
        TradovateResolvedContractCandidate(
            contract=contract,
            maturity=maturities[contract.contract_maturity_id],
        )
        for contract in contracts
        if contract.contract_maturity_id in maturities
    )
