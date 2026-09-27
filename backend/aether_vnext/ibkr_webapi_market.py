"""IBKR Web API top-of-book market-data transport for AETHER vNext.

Market data only. No order, account-mutation, or position-management methods exist
here.

Supported authentication surfaces:
- Client Portal Gateway: cookie header api=<session token>
- OAuth2 Web API: sessionToken query parameter

Both require an already-established IBKR brokerage session. This module does not
automate browser login or brokerage-session creation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import ssl
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from websockets.asyncio.client import connect as websocket_connect

from aether_vnext.market_data import RawQuote
from aether_vnext.shortability import (
    ShortabilityEvidence,
    build_shortability_evidence,
)


IBKR_WEBAPI_MARKET_SOURCE_ID = "ibkr_webapi_market_data"
IBKR_WEBAPI_TRANSPORT_ID = "ibkr_webapi_smd_websocket"
IBKR_WEBAPI_ADAPTER_VERSION = "ibkr_webapi_smd_v1:mid_mark_v1"
IBKR_CPGW_WEBSOCKET_URL = "wss://localhost:5000/v1/api/ws"
IBKR_MARKET_DATA_FIELDS = ("31", "84", "86", "6509")
IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID = "ibkr_webapi_shortability"
IBKR_WEBAPI_SHORTABILITY_ADAPTER_VERSION = "ibkr_webapi_shortability_smd_v1"
IBKR_SHORTABILITY_FIELDS = ("7636", "7637", "7644", "6509")


@dataclass(frozen=True, slots=True)
class IbkrTopOfBookBatch:
    websocket_url: str
    auth_mode: str
    requested_contract_ids: tuple[int, ...]
    message_count: int
    quotes: tuple[RawQuote, ...]


@dataclass(frozen=True, slots=True)
class IbkrShortabilityBatch:
    websocket_url: str
    auth_mode: str
    requested_contract_ids: tuple[int, ...]
    message_count: int
    evidence: tuple[ShortabilityEvidence, ...]


def market_data_subscription(
    *,
    contract_id: int,
    fields: tuple[str, ...] = IBKR_MARKET_DATA_FIELDS,
) -> str:
    if isinstance(contract_id, bool) or contract_id <= 0:
        raise ValueError("IBKR contract_id must be a positive integer")
    normalized = tuple(str(field).strip() for field in fields)
    if not normalized or any(not field for field in normalized):
        raise ValueError("IBKR market-data fields must be nonblank")
    return (
        f"smd+{int(contract_id)}+"
        + json.dumps(
            {"fields": list(normalized)},
            separators=(",", ":"),
        )
    )


def _decode(raw: str | bytes) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_price(value: object) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    prefix = None
    if text[0] in {"C", "H"}:
        prefix = text[0]
        text = text[1:].strip()
    try:
        price = float(text)
    except ValueError:
        return None, prefix
    return (price if price > 0 else None), prefix


def _updated_at_utc(value: object) -> datetime | None:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return None
    if milliseconds <= 0:
        return None
    return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)


def _availability_is_realtime(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and text[0] == "R"


def _merge_market_message(
    state: dict[str, object],
    payload: dict[str, Any],
) -> dict[str, object]:
    for key in ("31", "84", "86", "6509", "_updated", "conid", "conidEx"):
        if key in payload:
            state[key] = payload[key]
    return state


def _raw_quote_from_state(
    *,
    state: Mapping[str, object],
    asset_id: str,
    received_at_utc: datetime,
) -> RawQuote | None:
    if received_at_utc.tzinfo is None:
        raise ValueError("received_at_utc must be timezone-aware")
    if not _availability_is_realtime(state.get("6509")):
        return None

    bid, _ = _parse_price(state.get("84"))
    ask, _ = _parse_price(state.get("86"))
    last, last_prefix = _parse_price(state.get("31"))
    if last_prefix == "H":
        raise RuntimeError("ibkr_market_halted")
    if bid is None or ask is None or ask < bid:
        return None

    mark = (bid + ask) / 2.0
    exchange_ts = _updated_at_utc(state.get("_updated"))
    return RawQuote(
        asset_id=str(asset_id).strip().lower(),
        venue="IBKR",
        source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        bid=bid,
        ask=ask,
        last=last,
        mark=mark,
        exchange_ts=exchange_ts,
        received_ts=received_at_utc,
        adapter_version=IBKR_WEBAPI_ADAPTER_VERSION,
    )


def _oauth2_url(url: str, token: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["sessionToken"] = token
    return urlunparse(parsed._replace(query=urlencode(query)))


def _insecure_localhost_context(url: str) -> ssl.SSLContext:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(
            "insecure TLS is permitted only for localhost/loopback IBKR gateway"
        )
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def fetch_ibkr_top_of_book(
    *,
    asset_contract_ids: Mapping[str, int],
    session_token: str,
    auth_mode: str = "cpgw_cookie",
    websocket_url: str = IBKR_CPGW_WEBSOCKET_URL,
    timeout_s: float = 10.0,
    allow_insecure_localhost_tls: bool = False,
    connect_factory: Callable[..., Any] | None = None,
) -> IbkrTopOfBookBatch:
    """Collect one real-time top-of-book quote for each reviewed contract ID."""
    token = str(session_token).strip()
    if not token:
        raise ValueError("IBKR session token is required")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    normalized: dict[str, int] = {}
    for raw_asset, raw_contract_id in asset_contract_ids.items():
        asset_id = str(raw_asset).strip().lower()
        if not asset_id:
            raise ValueError("asset_id is required")
        if (
            isinstance(raw_contract_id, bool)
            or int(raw_contract_id) <= 0
        ):
            raise ValueError("IBKR contract IDs must be positive integers")
        normalized[asset_id] = int(raw_contract_id)
    if not normalized:
        raise ValueError("asset_contract_ids must be non-empty")
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("duplicate IBKR contract ID")

    mode = str(auth_mode).strip().lower()
    if mode not in {"cpgw_cookie", "oauth2_query"}:
        raise ValueError("IBKR auth_mode must be cpgw_cookie or oauth2_query")

    target_url = str(websocket_url).strip()
    if not target_url:
        raise ValueError("websocket_url is required")
    headers = None
    if mode == "cpgw_cookie":
        headers = {"Cookie": f"api={token}"}
    else:
        target_url = _oauth2_url(target_url, token)

    connect = connect_factory or websocket_connect
    kwargs: dict[str, object] = {
        "open_timeout": timeout_s,
        "close_timeout": 5.0,
        "ping_interval": 20.0,
        "ping_timeout": 20.0,
        "max_queue": 64,
    }
    if headers is not None:
        kwargs["additional_headers"] = headers
    if allow_insecure_localhost_tls:
        kwargs["ssl"] = _insecure_localhost_context(target_url)

    contract_to_asset = {
        contract_id: asset_id
        for asset_id, contract_id in normalized.items()
    }
    state_by_contract: dict[int, dict[str, object]] = {
        contract_id: {} for contract_id in contract_to_asset
    }
    latest_quotes: dict[int, RawQuote] = {}
    message_count = 0

    async with connect(target_url, **kwargs) as websocket:
        for contract_id in contract_to_asset:
            await websocket.send(
                market_data_subscription(contract_id=contract_id)
            )

        try:
            async with asyncio.timeout(timeout_s):
                while len(latest_quotes) < len(contract_to_asset):
                    raw = await websocket.recv()
                    message_count += 1
                    payload = _decode(raw)
                    if payload is None:
                        continue
                    try:
                        contract_id = int(payload.get("conid"))
                    except (TypeError, ValueError):
                        continue
                    asset_id = contract_to_asset.get(contract_id)
                    if asset_id is None:
                        continue

                    availability = payload.get("6509")
                    if availability is not None and not _availability_is_realtime(
                        availability
                    ):
                        raise RuntimeError(
                            "ibkr_market_data_not_realtime:"
                            + str(availability)
                        )

                    state = _merge_market_message(
                        state_by_contract[contract_id],
                        payload,
                    )
                    quote = _raw_quote_from_state(
                        state=state,
                        asset_id=asset_id,
                        received_at_utc=datetime.now(timezone.utc),
                    )
                    if quote is not None:
                        latest_quotes[contract_id] = quote
        except TimeoutError as exc:
            missing = sorted(
                contract_id
                for contract_id in contract_to_asset
                if contract_id not in latest_quotes
            )
            raise TimeoutError(
                "IBKR top-of-book sample timed out for contract IDs: "
                + ",".join(str(value) for value in missing)
            ) from exc

    ordered_contract_ids = tuple(normalized.values())
    return IbkrTopOfBookBatch(
        # Never return the OAuth2 query URL because it contains sessionToken.
        websocket_url=str(websocket_url).strip(),
        auth_mode=mode,
        requested_contract_ids=ordered_contract_ids,
        message_count=message_count,
        quotes=tuple(latest_quotes[value] for value in ordered_contract_ids),
    )


def _parse_nonnegative_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _shortability_from_state(
    *,
    state: Mapping[str, object],
    asset_id: str,
    contract_id: int,
    received_at_utc: datetime,
) -> ShortabilityEvidence | None:
    if received_at_utc.tzinfo is None:
        raise ValueError("received_at_utc must be timezone-aware")

    availability = str(state.get("6509") or "").strip()
    if not availability:
        return None
    if not _availability_is_realtime(availability):
        raise RuntimeError(
            "ibkr_shortability_not_realtime:" + availability
        )

    if any(
        field not in state
        for field in ("7636", "7637", "7644", "6509")
    ):
        return None

    shares = _parse_nonnegative_number(state.get("7636"))
    if shares is None:
        return None

    fee_rate_raw = (
        None
        if state.get("7637") is None
        else str(state.get("7637")).strip() or None
    )
    shortable_raw = (
        None
        if state.get("7644") is None
        else str(state.get("7644")).strip() or None
    )
    return build_shortability_evidence(
        asset_id=asset_id,
        provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        market_data_contract_id=contract_id,
        shortable_shares=shares,
        fee_rate_raw=fee_rate_raw,
        shortable_raw=shortable_raw,
        market_data_availability=availability,
        provider_updated_at_utc=_updated_at_utc(state.get("_updated")),
        received_at_utc=received_at_utc,
        adapter_version=IBKR_WEBAPI_SHORTABILITY_ADAPTER_VERSION,
    )


async def fetch_ibkr_shortability(
    *,
    asset_contract_ids: Mapping[str, int],
    session_token: str,
    auth_mode: str = "cpgw_cookie",
    websocket_url: str = IBKR_CPGW_WEBSOCKET_URL,
    timeout_s: float = 10.0,
    allow_insecure_localhost_tls: bool = False,
    connect_factory: Callable[..., Any] | None = None,
) -> IbkrShortabilityBatch:
    """Collect one real-time IBKR shortability observation per reviewed conid."""
    token = str(session_token).strip()
    if not token:
        raise ValueError("IBKR session token is required")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    normalized: dict[str, int] = {}
    for raw_asset, raw_contract_id in asset_contract_ids.items():
        asset_id = str(raw_asset).strip().lower()
        if not asset_id:
            raise ValueError("asset_id is required")
        if isinstance(raw_contract_id, bool) or int(raw_contract_id) <= 0:
            raise ValueError("IBKR contract IDs must be positive integers")
        normalized[asset_id] = int(raw_contract_id)
    if not normalized:
        raise ValueError("asset_contract_ids must be non-empty")
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("duplicate IBKR contract ID")

    mode = str(auth_mode).strip().lower()
    if mode not in {"cpgw_cookie", "oauth2_query"}:
        raise ValueError("IBKR auth_mode must be cpgw_cookie or oauth2_query")

    target_url = str(websocket_url).strip()
    if not target_url:
        raise ValueError("websocket_url is required")
    headers = None
    if mode == "cpgw_cookie":
        headers = {"Cookie": f"api={token}"}
    else:
        target_url = _oauth2_url(target_url, token)

    connect = connect_factory or websocket_connect
    kwargs: dict[str, object] = {
        "open_timeout": timeout_s,
        "close_timeout": 5.0,
        "ping_interval": 20.0,
        "ping_timeout": 20.0,
        "max_queue": 64,
    }
    if headers is not None:
        kwargs["additional_headers"] = headers
    if allow_insecure_localhost_tls:
        kwargs["ssl"] = _insecure_localhost_context(target_url)

    contract_to_asset = {
        contract_id: asset_id
        for asset_id, contract_id in normalized.items()
    }
    state_by_contract: dict[int, dict[str, object]] = {
        contract_id: {} for contract_id in contract_to_asset
    }
    evidence_by_contract: dict[int, ShortabilityEvidence] = {}
    message_count = 0

    async with connect(target_url, **kwargs) as websocket:
        for contract_id in contract_to_asset:
            await websocket.send(
                market_data_subscription(
                    contract_id=contract_id,
                    fields=IBKR_SHORTABILITY_FIELDS,
                )
            )

        try:
            async with asyncio.timeout(timeout_s):
                while len(evidence_by_contract) < len(contract_to_asset):
                    raw = await websocket.recv()
                    message_count += 1
                    payload = _decode(raw)
                    if payload is None:
                        continue
                    try:
                        contract_id = int(payload.get("conid"))
                    except (TypeError, ValueError):
                        continue
                    asset_id = contract_to_asset.get(contract_id)
                    if asset_id is None:
                        continue

                    state = state_by_contract[contract_id]
                    for key in (
                        "7636",
                        "7637",
                        "7644",
                        "6509",
                        "_updated",
                        "conid",
                        "conidEx",
                    ):
                        if key in payload:
                            state[key] = payload[key]

                    evidence = _shortability_from_state(
                        state=state,
                        asset_id=asset_id,
                        contract_id=contract_id,
                        received_at_utc=datetime.now(timezone.utc),
                    )
                    if evidence is not None:
                        evidence_by_contract[contract_id] = evidence
        except TimeoutError as exc:
            missing = sorted(
                contract_id
                for contract_id in contract_to_asset
                if contract_id not in evidence_by_contract
            )
            raise TimeoutError(
                "IBKR shortability sample timed out for contract IDs: "
                + ",".join(str(value) for value in missing)
            ) from exc

    ordered_contract_ids = tuple(normalized.values())
    return IbkrShortabilityBatch(
        websocket_url=str(websocket_url).strip(),
        auth_mode=mode,
        requested_contract_ids=ordered_contract_ids,
        message_count=message_count,
        evidence=tuple(
            evidence_by_contract[value] for value in ordered_contract_ids
        ),
    )
