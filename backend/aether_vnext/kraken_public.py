"""Kraken public WebSocket v2 transport for AETHER vNext market data.

This module is market-data infrastructure only. It has no private credentials,
order methods, strategy opinions, or execution authority.

Kraken public WebSocket v2:
- endpoint: wss://ws.kraken.com/v2
- ticker subscription: channel=ticker
- symbols: BTC/USD and ETH/USD for the current vNext crypto seed
- event_trigger=bbo so best-bid-offer changes drive updates
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping, Protocol

import websockets

from aether_vnext.adapters import KrakenPublicTickerV2, KrakenPublicTradeV2
from aether_vnext.bars import MarketPrint
from aether_vnext.market_data import RawQuote


KRAKEN_PUBLIC_WS_V2_URL = "wss://ws.kraken.com/v2"
KRAKEN_PUBLIC_TICKER_SOURCE_ID = KrakenPublicTickerV2.adapter_id
KRAKEN_PUBLIC_TRADE_SOURCE_ID = KrakenPublicTradeV2.adapter_id

CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL = {
    "btc": "BTC/USD",
    "eth": "ETH/USD",
}
KRAKEN_V2_SYMBOL_TO_CRYPTO_ASSET = {
    symbol: asset_id
    for asset_id, symbol in CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL.items()
}


class _WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


@dataclass(frozen=True, slots=True)
class KrakenTickerBatch:
    endpoint: str
    requested_symbols: tuple[str, ...]
    status_system: str
    status_api_version: str | None
    connection_id: int | None
    subscription_acknowledged: bool
    heartbeat_count: int
    message_count: int
    quotes: tuple[RawQuote, ...]


@dataclass(frozen=True, slots=True)
class KrakenTradeBatch:
    endpoint: str
    requested_symbols: tuple[str, ...]
    status_system: str
    status_api_version: str | None
    connection_id: int | None
    subscription_acknowledged: bool
    heartbeat_count: int
    message_count: int
    prints: tuple[MarketPrint, ...]


def kraken_ticker_subscription(
    *,
    symbols: tuple[str, ...],
    req_id: int = 1,
    allowed_symbols: frozenset[str] | None = None,
) -> dict[str, Any]:
    if not symbols:
        raise ValueError("at least one Kraken symbol is required")
    requested = tuple(str(symbol).strip() for symbol in symbols)
    if any(not symbol for symbol in requested):
        raise ValueError("Kraken symbols must be nonblank")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate Kraken symbol")
    allowed = (
        frozenset(KRAKEN_V2_SYMBOL_TO_CRYPTO_ASSET)
        if allowed_symbols is None
        else allowed_symbols
    )
    unsupported = tuple(
        symbol
        for symbol in requested
        if symbol not in allowed
    )
    if unsupported:
        raise ValueError(
            "unsupported AETHER Kraken v2 symbol(s): "
            + ",".join(unsupported)
        )
    return {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": list(requested),
            "event_trigger": "bbo",
            "snapshot": True,
        },
        "req_id": int(req_id),
    }


def kraken_trade_subscription(
    *,
    symbols: tuple[str, ...],
    req_id: int = 2,
) -> dict[str, Any]:
    if not symbols:
        raise ValueError("at least one Kraken symbol is required")
    requested = tuple(str(symbol).strip() for symbol in symbols)
    if any(not symbol for symbol in requested):
        raise ValueError("Kraken symbols must be nonblank")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate Kraken symbol")
    unsupported = tuple(
        symbol
        for symbol in requested
        if symbol not in KRAKEN_V2_SYMBOL_TO_CRYPTO_ASSET
    )
    if unsupported:
        raise ValueError(
            "unsupported AETHER Kraken v2 symbol(s): "
            + ",".join(unsupported)
        )
    return {
        "method": "subscribe",
        "params": {
            "channel": "trade",
            "symbol": list(requested),
            # Runtime must begin with new matched trades only; a 50-trade
            # subscription snapshot would replay pre-subscription history.
            "snapshot": False,
        },
        "req_id": int(req_id),
    }


def _decode_message(raw: str | bytes) -> dict[str, Any] | None:
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


def _status_from_message(
    payload: dict[str, Any],
) -> tuple[str, str | None, int | None] | None:
    if payload.get("channel") != "status":
        return None
    rows = payload.get("data") or ()
    if not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    system = str(row.get("system") or "").strip().lower()
    if not system:
        return None
    api_version_raw = row.get("api_version")
    connection_id_raw = row.get("connection_id")
    connection_id = None
    if connection_id_raw is not None:
        try:
            connection_id = int(connection_id_raw)
        except (TypeError, ValueError):
            connection_id = None
    return (
        system,
        None if api_version_raw is None else str(api_version_raw),
        connection_id,
    )


def _subscription_ack(
    payload: dict[str, Any],
    *,
    expected_channel: str = "ticker",
) -> tuple[bool, str | None] | None:
    if payload.get("method") != "subscribe":
        return None
    success = payload.get("success")
    if success is None:
        return None
    if bool(success):
        result = payload.get("result")
        if isinstance(result, dict):
            if result.get("channel") not in (None, expected_channel):
                return None
        return True, None
    return False, str(payload.get("error") or "unknown_subscription_error")


async def _collect_from_socket(
    websocket: _WebSocketLike,
    *,
    symbols: tuple[str, ...],
    symbol_to_asset: Mapping[str, str],
    timeout_s: float,
    adapter: KrakenPublicTickerV2,
) -> KrakenTickerBatch:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    await websocket.send(
        json.dumps(
            kraken_ticker_subscription(
                symbols=symbols,
                allowed_symbols=frozenset(symbol_to_asset),
            ),
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    requested_assets = {
        str(symbol_to_asset[symbol]).strip().lower()
        for symbol in symbols
    }
    latest_quotes: dict[str, RawQuote] = {}
    status_system: str | None = None
    status_api_version: str | None = None
    connection_id: int | None = None
    subscription_acknowledged = False
    heartbeat_count = 0
    message_count = 0

    async with asyncio.timeout(timeout_s):
        while True:
            raw = await websocket.recv()
            message_count += 1
            received_at_utc = datetime.now(timezone.utc)
            payload = _decode_message(raw)
            if payload is None:
                continue

            if payload.get("channel") == "heartbeat":
                heartbeat_count += 1
                continue

            status = _status_from_message(payload)
            if status is not None:
                status_system, status_api_version, connection_id = status
                if status_system != "online":
                    raise RuntimeError(
                        f"kraken_exchange_status:{status_system}"
                    )
                continue

            ack = _subscription_ack(payload)
            if ack is not None:
                success, error = ack
                if not success:
                    raise RuntimeError(
                        f"kraken_ticker_subscription_failed:{error}"
                    )
                subscription_acknowledged = True
                continue

            for quote in adapter.parse_quote(
                payload,
                received_at_utc=received_at_utc,
            ):
                if quote.asset_id in requested_assets:
                    latest_quotes[quote.asset_id] = quote

            complete_quotes = requested_assets <= set(latest_quotes)
            if (
                complete_quotes
                and subscription_acknowledged
                and status_system == "online"
            ):
                ordered = tuple(
                    latest_quotes[
                        str(symbol_to_asset[symbol]).strip().lower()
                    ]
                    for symbol in symbols
                )
                return KrakenTickerBatch(
                    endpoint=KRAKEN_PUBLIC_WS_V2_URL,
                    requested_symbols=symbols,
                    status_system=status_system,
                    status_api_version=status_api_version,
                    connection_id=connection_id,
                    subscription_acknowledged=True,
                    heartbeat_count=heartbeat_count,
                    message_count=message_count,
                    quotes=ordered,
                )


async def _collect_trades_from_socket(
    websocket: _WebSocketLike,
    *,
    symbols: tuple[str, ...],
    timeout_s: float,
    adapter: KrakenPublicTradeV2,
) -> KrakenTradeBatch:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    await websocket.send(
        json.dumps(
            kraken_trade_subscription(symbols=symbols),
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    requested_assets = {
        KRAKEN_V2_SYMBOL_TO_CRYPTO_ASSET[symbol]
        for symbol in symbols
    }
    observed_assets: set[str] = set()
    prints: list[MarketPrint] = []
    status_system: str | None = None
    status_api_version: str | None = None
    connection_id: int | None = None
    subscription_acknowledged = False
    heartbeat_count = 0
    message_count = 0

    async with asyncio.timeout(timeout_s):
        while True:
            raw = await websocket.recv()
            message_count += 1
            received_at_utc = datetime.now(timezone.utc)
            payload = _decode_message(raw)
            if payload is None:
                continue

            if payload.get("channel") == "heartbeat":
                heartbeat_count += 1
                continue

            status = _status_from_message(payload)
            if status is not None:
                status_system, status_api_version, connection_id = status
                if status_system != "online":
                    raise RuntimeError(
                        f"kraken_exchange_status:{status_system}"
                    )
                continue

            ack = _subscription_ack(
                payload,
                expected_channel="trade",
            )
            if ack is not None:
                success, error = ack
                if not success:
                    raise RuntimeError(
                        f"kraken_trade_subscription_failed:{error}"
                    )
                subscription_acknowledged = True
                continue

            parsed = adapter.parse_prints(
                payload,
                received_at_utc=received_at_utc,
            )
            for print_ in parsed:
                if print_.asset_id not in requested_assets:
                    continue
                prints.append(print_)
                observed_assets.add(print_.asset_id)

            if (
                requested_assets <= observed_assets
                and subscription_acknowledged
                and status_system == "online"
            ):
                ordered = tuple(
                    sorted(
                        prints,
                        key=lambda row: (
                            row.exchange_ts,
                            row.asset_id,
                            row.price,
                            row.volume,
                        ),
                    )
                )
                return KrakenTradeBatch(
                    endpoint=KRAKEN_PUBLIC_WS_V2_URL,
                    requested_symbols=symbols,
                    status_system=status_system,
                    status_api_version=status_api_version,
                    connection_id=connection_id,
                    subscription_acknowledged=True,
                    heartbeat_count=heartbeat_count,
                    message_count=message_count,
                    prints=ordered,
                )


async def fetch_kraken_public_trades(
    *,
    assets: tuple[str, ...] = ("btc", "eth"),
    timeout_s: float = 15.0,
    connect_factory: Callable[..., Any] | None = None,
) -> KrakenTradeBatch:
    """Fetch at least one new matched trade for every requested crypto asset."""
    requested_assets = tuple(str(asset).strip().lower() for asset in assets)
    if not requested_assets:
        raise ValueError("at least one asset is required")
    if len(requested_assets) != len(set(requested_assets)):
        raise ValueError("duplicate asset_id")
    unknown = tuple(
        asset
        for asset in requested_assets
        if asset not in CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL
    )
    if unknown:
        raise ValueError(
            "unsupported AETHER Kraken asset(s): " + ",".join(unknown)
        )

    symbols = tuple(
        CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL[asset]
        for asset in requested_assets
    )
    adapter = KrakenPublicTradeV2()
    connect = connect_factory or websockets.connect

    async with connect(
        KRAKEN_PUBLIC_WS_V2_URL,
        open_timeout=timeout_s,
        close_timeout=5.0,
        ping_interval=20.0,
        ping_timeout=20.0,
        max_queue=256,
    ) as websocket:
        try:
            return await _collect_trades_from_socket(
                websocket,
                symbols=symbols,
                timeout_s=timeout_s,
                adapter=adapter,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                "Kraken trade sample timed out before status, subscription "
                "acknowledgement, and at least one new trade for every "
                "requested asset were observed"
            ) from exc


async def fetch_kraken_public_tickers(
    *,
    assets: tuple[str, ...] = ("btc", "eth"),
    symbol_by_asset: Mapping[str, str] | None = None,
    timeout_s: float = 10.0,
    connect_factory: Callable[..., Any] | None = None,
) -> KrakenTickerBatch:
    """Fetch one current BBO-driven ticker observation for every requested asset."""
    requested_assets = tuple(str(asset).strip().lower() for asset in assets)
    if not requested_assets:
        raise ValueError("at least one asset is required")
    if len(requested_assets) != len(set(requested_assets)):
        raise ValueError("duplicate asset_id")
    if symbol_by_asset is None:
        mapping = {
            asset: CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL[asset]
            for asset in requested_assets
            if asset in CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL
        }
    else:
        mapping = {
            str(asset).strip().lower(): str(symbol).strip()
            for asset, symbol in symbol_by_asset.items()
        }

    unknown = tuple(
        asset for asset in requested_assets if asset not in mapping
    )
    if unknown:
        raise ValueError(
            "unsupported AETHER Kraken asset(s): " + ",".join(unknown)
        )
    if any(not mapping[asset] for asset in requested_assets):
        raise ValueError("Kraken provider symbols must be nonblank")

    symbols = tuple(mapping[asset] for asset in requested_assets)
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate Kraken provider symbol")
    symbol_to_asset = {
        mapping[asset]: asset
        for asset in requested_assets
    }
    adapter = KrakenPublicTickerV2(pair_to_asset=symbol_to_asset)
    connect = connect_factory or websockets.connect

    async with connect(
        KRAKEN_PUBLIC_WS_V2_URL,
        open_timeout=timeout_s,
        close_timeout=5.0,
        ping_interval=20.0,
        ping_timeout=20.0,
        max_queue=64,
    ) as websocket:
        try:
            return await _collect_from_socket(
                websocket,
                symbols=symbols,
                symbol_to_asset=symbol_to_asset,
                timeout_s=timeout_s,
                adapter=adapter,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                "Kraken ticker sample timed out before status, "
                "subscription acknowledgement, and all requested quotes "
                "were observed"
            ) from exc
