"""DEMO-only NinjaTrader market-data transport for AETHER vNext.

This transport consumes a market-data-only credential payload containing only
mdAccessToken plus the authoritative apiHosts.mdDemo host. It deliberately refuses
a trading accessToken or live market-data host material.

One WebSocket connection is scoped to one reviewed futures binding. The subscribed
contract symbol and the provider's numeric contractId must both match the frozen
runtime binding before a RawQuote can leave this boundary.

No order, account, position, or live-trading endpoints exist in this module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Protocol

import websockets

from aether_vnext.bars import MarketPrint
from aether_vnext.market_data import RawQuote
from aether_vnext.ninjatrader_market import (
    NINJATRADER_DEMO_ADAPTER_VERSION,
    NINJATRADER_HEARTBEAT_REPLY,
    NINJATRADER_MARKET_SOURCE_ID,
    authorize_market_data_request,
    decode_server_frame,
    parse_quote_events,
    parse_trade_prints,
    require_success_response,
    response_for_request,
    subscribe_quote_request,
)
from aether_vnext.registry import registry_row
from aether_vnext.registry_runtime import (
    RuntimeRegistryBinding,
    binding_blockers,
)


_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_FUTURES_ASSETS = frozenset({"mes", "mnq", "mgc", "mcl", "us10y"})


class _WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


@dataclass(frozen=True, slots=True)
class NinjaTraderDemoMarketAuth:
    md_access_token: str
    md_demo_host: str
    expiration_time_utc: datetime | None = None

    def __post_init__(self) -> None:
        token = str(self.md_access_token).strip()
        host = str(self.md_demo_host).strip()
        if not token or "\n" in token:
            raise ValueError("md_access_token must be one nonblank line")
        if (
            not host
            or "://" in host
            or "/" in host
            or ":" in host
            or not _HOST_RE.fullmatch(host)
        ):
            raise ValueError(
                "md_demo_host must be the bare hostname returned as apiHosts.mdDemo"
            )
        if (
            self.expiration_time_utc is not None
            and self.expiration_time_utc.tzinfo is None
        ):
            raise ValueError("expiration_time_utc must be timezone-aware")

    @property
    def websocket_url(self) -> str:
        return f"wss://{self.md_demo_host}/v1/websocket"

    def assert_valid_at(self, at_utc: datetime) -> None:
        if at_utc.tzinfo is None:
            raise ValueError("at_utc must be timezone-aware")
        if (
            self.expiration_time_utc is not None
            and at_utc >= self.expiration_time_utc
        ):
            raise RuntimeError("NinjaTrader DEMO mdAccessToken is expired")

    @classmethod
    def from_market_only_payload(
        cls,
        payload: dict[str, Any],
    ) -> "NinjaTraderDemoMarketAuth":
        if not isinstance(payload, dict):
            raise ValueError("NinjaTrader market auth payload must be an object")

        # Never allow the trading REST/WebSocket token into this market-data-only
        # boundary. The caller must sanitize the authentication result.
        prohibited = {
            "accessToken",
            "live",
            "demo",
            "mdLive",
            "reportingLive",
            "reportingDemo",
            "adminLive",
            "adminDemo",
        }
        if prohibited.intersection(payload):
            raise ValueError(
                "market-data-only payload contains prohibited trading/live fields"
            )

        hosts = payload.get("apiHosts")
        if not isinstance(hosts, dict):
            raise ValueError("apiHosts is required")
        if any(key != "mdDemo" for key in hosts):
            raise ValueError(
                "market-data-only apiHosts may contain mdDemo only"
            )

        expiration_raw = payload.get("expirationTime")
        expiration = None
        if expiration_raw not in (None, ""):
            try:
                expiration = datetime.fromisoformat(
                    str(expiration_raw).replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError("expirationTime is invalid") from exc

        return cls(
            md_access_token=str(payload.get("mdAccessToken") or ""),
            md_demo_host=str(hosts.get("mdDemo") or ""),
            expiration_time_utc=expiration,
        )


@dataclass(frozen=True, slots=True)
class NinjaTraderDemoQuoteSample:
    asset_id: str
    current_contract: str
    contract_id: int
    endpoint: str
    quote: RawQuote
    heartbeat_count: int
    message_count: int
    trade_print: MarketPrint | None = None


async def _wait_for_response(
    websocket: _WebSocketLike,
    *,
    request_id: int,
    operation: str,
) -> tuple[int, int]:
    """Wait for one response while satisfying provider heartbeat obligations."""
    heartbeat_count = 0
    message_count = 0
    while True:
        frame = decode_server_frame(await websocket.recv())
        message_count += 1
        if frame.frame_type == "h":
            heartbeat_count += 1
            await websocket.send(NINJATRADER_HEARTBEAT_REPLY)
            continue
        if frame.frame_type == "c":
            raise RuntimeError(
                f"NinjaTrader socket closed during {operation}: "
                f"{frame.close_payload}"
            )
        if frame.frame_type != "a":
            continue
        if response_for_request(frame.messages, request_id=request_id) is None:
            continue
        require_success_response(
            frame.messages,
            request_id=request_id,
            operation=operation,
        )
        return heartbeat_count, message_count


async def fetch_ninjatrader_demo_quote(
    *,
    binding: RuntimeRegistryBinding,
    auth: NinjaTraderDemoMarketAuth,
    timeout_s: float = 10.0,
    require_trade_print: bool = False,
    connect_factory: Callable[..., Any] | None = None,
) -> NinjaTraderDemoQuoteSample:
    """Fetch one contract-ID-locked DEMO quote for one reviewed futures binding."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    now = datetime.now(timezone.utc)
    auth.assert_valid_at(now)

    asset_id = binding.asset_id.strip().lower()
    if asset_id not in _FUTURES_ASSETS:
        raise ValueError("NinjaTrader DEMO quote transport accepts futures only")
    if binding.primary_market_source_id != NINJATRADER_MARKET_SOURCE_ID:
        raise ValueError(
            "runtime binding primary source is not NinjaTrader market data"
        )

    blockers = binding_blockers(
        binding,
        as_of_utc=now,
        require_market_source_implementation=False,
    )
    if blockers:
        raise ValueError(
            "runtime futures binding is incomplete: " + ",".join(blockers)
        )
    if binding.current_contract is None:
        raise RuntimeError("current_contract unexpectedly absent")
    if binding.market_data_contract_id is None:
        raise RuntimeError("market_data_contract_id unexpectedly absent")

    base = registry_row(asset_id)
    expected_contract_id = int(binding.market_data_contract_id)
    connect = connect_factory or websockets.connect

    try:
        async with asyncio.timeout(timeout_s):
            async with connect(
                auth.websocket_url,
                open_timeout=timeout_s,
                close_timeout=5.0,
                ping_interval=None,
                max_queue=64,
            ) as websocket:
                heartbeat_count = 0
                message_count = 0

                # The protocol requires an explicit server open frame before use.
                while True:
                    frame = decode_server_frame(await websocket.recv())
                    message_count += 1
                    if frame.frame_type == "h":
                        heartbeat_count += 1
                        await websocket.send(NINJATRADER_HEARTBEAT_REPLY)
                        continue
                    if frame.frame_type == "c":
                        raise RuntimeError(
                            "NinjaTrader socket closed before open: "
                            f"{frame.close_payload}"
                        )
                    if frame.frame_type == "o":
                        break

                await websocket.send(
                    authorize_market_data_request(
                        md_access_token=auth.md_access_token,
                        request_id=1,
                    )
                )
                h, m = await _wait_for_response(
                    websocket,
                    request_id=1,
                    operation="authorize",
                )
                heartbeat_count += h
                message_count += m

                await websocket.send(
                    subscribe_quote_request(
                        symbol=binding.current_contract,
                        request_id=2,
                    )
                )
                h, m = await _wait_for_response(
                    websocket,
                    request_id=2,
                    operation="md/subscribeQuote",
                )
                heartbeat_count += h
                message_count += m

                bid: float | None = None
                ask: float | None = None
                last: float | None = None
                exchange_ts: datetime | None = None
                trade_print: MarketPrint | None = None

                while True:
                    raw_frame = await websocket.recv()
                    received_at = datetime.now(timezone.utc)
                    frame = decode_server_frame(raw_frame)
                    message_count += 1
                    if frame.frame_type == "h":
                        heartbeat_count += 1
                        await websocket.send(NINJATRADER_HEARTBEAT_REPLY)
                        continue
                    if frame.frame_type == "c":
                        raise RuntimeError(
                            "NinjaTrader socket closed before a complete quote: "
                            f"{frame.close_payload}"
                        )
                    if frame.frame_type != "a":
                        continue

                    prints = parse_trade_prints(
                        frame.messages,
                        contract_to_asset={expected_contract_id: asset_id},
                        received_at_utc=received_at,
                    )
                    if prints:
                        trade_print = prints[-1]

                    for event in parse_quote_events(frame.messages):
                        if event.contract_id != expected_contract_id:
                            raise RuntimeError(
                                "NinjaTrader quote contractId does not match "
                                "the frozen runtime binding"
                            )
                        if event.bid is not None:
                            bid = event.bid
                        if event.ask is not None:
                            ask = event.ask
                        if event.last is not None:
                            last = event.last
                        exchange_ts = event.timestamp_utc

                    if bid is None or ask is None or exchange_ts is None:
                        continue
                    if require_trade_print and trade_print is None:
                        continue

                    quote = RawQuote(
                        asset_id=asset_id,
                        venue=base.venue,
                        source_id=NINJATRADER_MARKET_SOURCE_ID,
                        bid=bid,
                        ask=ask,
                        last=last,
                        mark=(bid + ask) / 2.0,
                        exchange_ts=exchange_ts,
                        received_ts=received_at,
                        adapter_version=NINJATRADER_DEMO_ADAPTER_VERSION,
                    )
                    return NinjaTraderDemoQuoteSample(
                        asset_id=asset_id,
                        current_contract=binding.current_contract,
                        contract_id=expected_contract_id,
                        endpoint=auth.websocket_url,
                        quote=quote,
                        heartbeat_count=heartbeat_count,
                        message_count=message_count,
                        trade_print=trade_print,
                    )
    except TimeoutError as exc:
        raise TimeoutError(
            "NinjaTrader DEMO quote sample timed out before the required "
            + (
                "contract-ID-locked BBO + provider trade print were observed"
                if require_trade_print
                else "contract-ID-locked BBO was observed"
            )
        ) from exc
