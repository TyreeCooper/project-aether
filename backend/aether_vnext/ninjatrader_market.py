"""NinjaTrader market-data WebSocket protocol boundary for AETHER vNext.

This module implements only the documented market-data framing/parsing surface:
SockJS-style server frames, client request framing, mdAccessToken authorization,
md/subscribeQuote, heartbeat replies, and quote-event decoding.

It deliberately contains no order, position, account, or live-trading methods.
A parsed NinjaTrader quote is not yet a canonical RawQuote because the provider event
identifies a contract by contractId. Asset/contract identity must be resolved and
frozen separately before this source can become burn-in operational.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Mapping

from aether_vnext.bars import MarketPrint


NINJATRADER_HEARTBEAT_REPLY = "[]"
NINJATRADER_MARKET_SOURCE_ID = "ninjatrader_market_data"
NINJATRADER_DEMO_TRANSPORT_ID = "ninjatrader_demo_market_websocket"
NINJATRADER_DEMO_ADAPTER_VERSION = (
    "ninjatrader_md_demo_quote_v1:contract_id_locked"
)
NINJATRADER_MARKET_PRINT_ADAPTER_VERSION = (
    "ninjatrader_md_demo_trade_v1:contract_id_locked"
)


@dataclass(frozen=True, slots=True)
class NinjaTraderSocketFrame:
    frame_type: str
    messages: tuple[dict[str, Any], ...] = ()
    close_payload: object | None = None


@dataclass(frozen=True, slots=True)
class NinjaTraderQuoteEvent:
    contract_id: int
    timestamp_utc: datetime
    bid: float | None
    ask: float | None
    last: float | None

    def __post_init__(self) -> None:
        if self.contract_id <= 0:
            raise ValueError("contract_id must be positive")
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        for name, value in (
            ("bid", self.bid),
            ("ask", self.ask),
            ("last", self.last),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when present")


def encode_request(
    *,
    endpoint: str,
    request_id: int,
    query: str | None = None,
    body: str | dict[str, Any] | None = None,
) -> str:
    """Encode the documented four-field newline-delimited WebSocket request."""
    endpoint_value = str(endpoint).strip()
    if not endpoint_value or "\n" in endpoint_value:
        raise ValueError("endpoint must be one nonblank line")
    if request_id <= 0:
        raise ValueError("request_id must be positive")

    query_value = "" if query is None else str(query)
    if "\n" in query_value:
        raise ValueError("query must be one line")

    if body is None:
        body_value = ""
    elif isinstance(body, dict):
        body_value = json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        body_value = str(body)
    if "\n" in body_value:
        raise ValueError("body must be one line")

    return "\n".join(
        (endpoint_value, str(int(request_id)), query_value, body_value)
    )


def authorize_market_data_request(
    *,
    md_access_token: str,
    request_id: int = 1,
) -> str:
    token = str(md_access_token).strip()
    if not token or "\n" in token:
        raise ValueError("md_access_token must be one nonblank line")
    return encode_request(
        endpoint="authorize",
        request_id=request_id,
        body=token,
    )


def subscribe_quote_request(
    *,
    symbol: str | int,
    request_id: int,
) -> str:
    if isinstance(symbol, bool):
        raise ValueError("symbol must be a contract symbol or contract ID")
    if isinstance(symbol, int):
        if symbol <= 0:
            raise ValueError("contract ID must be positive")
        normalized: str | int = symbol
    else:
        normalized = str(symbol).strip()
        if not normalized or "\n" in normalized:
            raise ValueError("contract symbol must be one nonblank line")
    return encode_request(
        endpoint="md/subscribeQuote",
        request_id=request_id,
        body={"symbol": normalized},
    )


def unsubscribe_quote_request(
    *,
    symbol: str | int,
    request_id: int,
) -> str:
    if isinstance(symbol, bool):
        raise ValueError("symbol must be a contract symbol or contract ID")
    if isinstance(symbol, int):
        if symbol <= 0:
            raise ValueError("contract ID must be positive")
        normalized: str | int = symbol
    else:
        normalized = str(symbol).strip()
        if not normalized or "\n" in normalized:
            raise ValueError("contract symbol must be one nonblank line")
    return encode_request(
        endpoint="md/unsubscribeQuote",
        request_id=request_id,
        body={"symbol": normalized},
    )


def decode_server_frame(raw: str | bytes) -> NinjaTraderSocketFrame:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    text = str(raw)
    if not text:
        raise ValueError("empty NinjaTrader WebSocket frame")

    frame_type = text[0]
    payload_text = text[1:]

    if frame_type in {"o", "h"}:
        if payload_text:
            raise ValueError(
                f"unexpected payload on NinjaTrader {frame_type!r} frame"
            )
        return NinjaTraderSocketFrame(frame_type=frame_type)

    if frame_type == "a":
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid NinjaTrader array frame JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("NinjaTrader array frame payload must be a list")
        messages = tuple(
            row for row in payload if isinstance(row, dict)
        )
        return NinjaTraderSocketFrame(
            frame_type=frame_type,
            messages=messages,
        )

    if frame_type == "c":
        try:
            close_payload = (
                None if not payload_text else json.loads(payload_text)
            )
        except json.JSONDecodeError as exc:
            raise ValueError("invalid NinjaTrader close frame JSON") from exc
        return NinjaTraderSocketFrame(
            frame_type=frame_type,
            close_payload=close_payload,
        )

    raise ValueError(f"unknown NinjaTrader WebSocket frame type: {frame_type}")


def response_for_request(
    messages: tuple[dict[str, Any], ...],
    *,
    request_id: int,
) -> dict[str, Any] | None:
    for message in messages:
        try:
            message_id = int(message.get("i"))
        except (TypeError, ValueError):
            continue
        if message_id == request_id and "s" in message:
            return message
    return None


def require_success_response(
    messages: tuple[dict[str, Any], ...],
    *,
    request_id: int,
    operation: str,
) -> dict[str, Any]:
    response = response_for_request(messages, request_id=request_id)
    if response is None:
        raise LookupError(
            f"NinjaTrader response not observed for {operation}:{request_id}"
        )
    try:
        status = int(response["s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("NinjaTrader response status is invalid") from exc
    if status < 200 or status >= 300:
        detail = response.get("d")
        raise RuntimeError(
            f"NinjaTrader {operation} failed with status {status}: {detail}"
        )
    return response


def _positive_price(entry: object) -> float | None:
    if not isinstance(entry, dict):
        return None
    try:
        value = float(entry["price"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _positive_size(entry: object) -> float | None:
    if not isinstance(entry, dict):
        return None
    try:
        value = float(entry["size"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def parse_quote_events(
    messages: tuple[dict[str, Any], ...],
) -> tuple[NinjaTraderQuoteEvent, ...]:
    """Decode provider quote events without guessing contract-to-asset identity."""
    out: list[NinjaTraderQuoteEvent] = []
    for message in messages:
        if message.get("e") != "md":
            continue
        data = message.get("d")
        if not isinstance(data, dict):
            continue
        for quote in data.get("quotes") or ():
            if not isinstance(quote, dict):
                continue
            try:
                contract_id = int(quote["contractId"])
            except (KeyError, TypeError, ValueError):
                continue
            timestamp = _parse_timestamp(quote.get("timestamp"))
            if contract_id <= 0 or timestamp is None:
                continue
            entries = quote.get("entries")
            if not isinstance(entries, dict):
                continue
            bid = _positive_price(entries.get("Bid"))
            ask = _positive_price(entries.get("Offer"))
            last = _positive_price(entries.get("Trade"))
            if bid is None and ask is None and last is None:
                continue
            out.append(
                NinjaTraderQuoteEvent(
                    contract_id=contract_id,
                    timestamp_utc=timestamp,
                    bid=bid,
                    ask=ask,
                    last=last,
                )
            )
    return tuple(out)


def parse_trade_prints(
    messages: tuple[dict[str, Any], ...],
    *,
    contract_to_asset: Mapping[int, str],
    received_at_utc: datetime,
) -> tuple[MarketPrint, ...]:
    """Decode documented Trade entries into canonical exchange-timestamp prints.

    NinjaTrader/Tradovate quote messages carry a Trade entry with both price and
    size. Contract identity remains explicit: callers must provide the reviewed
    contractId -> AETHER asset mapping, so this parser never guesses symbols.
    """
    if received_at_utc.tzinfo is None:
        raise ValueError("received_at_utc must be timezone-aware")

    normalized: dict[int, str] = {}
    for raw_contract_id, raw_asset_id in contract_to_asset.items():
        if isinstance(raw_contract_id, bool):
            raise ValueError("contract IDs must be positive integers")
        contract_id = int(raw_contract_id)
        asset_id = str(raw_asset_id).strip().lower()
        if contract_id <= 0:
            raise ValueError("contract IDs must be positive integers")
        if not asset_id:
            raise ValueError("asset_id must be nonblank")
        normalized[contract_id] = asset_id

    out: list[MarketPrint] = []
    for message in messages:
        if message.get("e") != "md":
            continue
        data = message.get("d")
        if not isinstance(data, dict):
            continue
        for quote in data.get("quotes") or ():
            if not isinstance(quote, dict):
                continue
            try:
                contract_id = int(quote["contractId"])
            except (KeyError, TypeError, ValueError):
                continue
            asset_id = normalized.get(contract_id)
            if asset_id is None:
                continue
            timestamp = _parse_timestamp(quote.get("timestamp"))
            entries = quote.get("entries")
            if timestamp is None or not isinstance(entries, dict):
                continue
            trade = entries.get("Trade")
            price = _positive_price(trade)
            size = _positive_size(trade)
            if price is None or size is None:
                continue
            out.append(
                MarketPrint(
                    asset_id=asset_id,
                    price=price,
                    volume=size,
                    exchange_ts=timestamp,
                    received_ts=received_at_utc,
                    source_id=NINJATRADER_MARKET_SOURCE_ID,
                )
            )
    return tuple(out)
