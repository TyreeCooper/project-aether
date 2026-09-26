"""AETHER vNext market-data adapter boundary.

Adapters may translate provider payloads into RawQuote/MarketPrint objects. They may
not emit setups, tickets, trades, or strategy opinions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from aether_vnext.market_data import RawQuote


class MarketDataAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def parse_quote(
        self,
        payload: Any,
        *,
        received_at_utc: datetime,
    ) -> tuple[RawQuote, ...]: ...


class KrakenPublicTickerV2:
    """Parser-only vNext adapter for Kraken public ticker v2 payloads."""

    adapter_id = "kraken_public"
    adapter_version = "kraken_public_ticker_v2:mid_mark_v1"

    _PAIR_TO_ASSET = {
        "BTC/USD": "btc",
        "XBT/USD": "btc",
        "ETH/USD": "eth",
    }

    def parse_quote(
        self,
        payload: Any,
        *,
        received_at_utc: datetime,
    ) -> tuple[RawQuote, ...]:
        if received_at_utc.tzinfo is None:
            raise ValueError("received_at_utc must be timezone-aware")
        if not isinstance(payload, dict) or payload.get("channel") != "ticker":
            return ()

        out: list[RawQuote] = []
        for row in payload.get("data") or ():
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            asset_id = self._PAIR_TO_ASSET.get(symbol)
            if asset_id is None:
                continue
            try:
                last = float(row["last"])
                bid = float(row["bid"])
                ask = float(row["ask"])
            except (KeyError, TypeError, ValueError):
                continue
            if last <= 0 or bid <= 0 or ask <= 0:
                continue

            # Adapter-level mark normalization is explicit/versioned. Firm P&L and
            # stop testing still use bid/ask conservatively per the Master.
            mark = (bid + ask) / 2.0

            exchange_ts = _parse_optional_timestamp(
                row.get("timestamp") or row.get("time")
            )
            out.append(
                RawQuote(
                    asset_id=asset_id,
                    venue="Kraken",
                    source_id=self.adapter_id,
                    bid=bid,
                    ask=ask,
                    last=last,
                    mark=mark,
                    exchange_ts=exchange_ts,
                    received_ts=received_at_utc,
                    adapter_version=self.adapter_version,
                )
            )
        return tuple(out)


def _parse_optional_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
