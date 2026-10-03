"""Concrete source adapters for the independent AETHER Consensus Tape.

Market-data sources are intentionally separate from execution providers. Public crypto
feeds can contribute without credentials. Databento GLBX is an independent,
credential-gated futures source; absence of its API key is reported as NOT_OBSERVED
and never replaced with synthetic market truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from typing import Any, Final, Mapping

from aether_vnext.tape import TapeSourceObservation, TapeSourceQuality


UTC = timezone.utc
KRAKEN_TAPE_SOURCE_ID: Final = "kraken_public_tape"
COINBASE_TAPE_SOURCE_ID: Final = "coinbase_exchange_tape"
BINANCE_US_TAPE_SOURCE_ID: Final = "binance_us_tape"
DATABENTO_GLBX_TAPE_SOURCE_ID: Final = "databento_glbx_mbp1"

COINBASE_EXCHANGE_WS: Final = "wss://ws-feed.exchange.coinbase.com"
KRAKEN_REST_TICKER: Final = "https://api.kraken.com/0/public/Ticker"
BINANCE_US_BOOK_TICKER: Final = "https://api.binance.us/api/v3/ticker/bookTicker"
DATABENTO_GLBX_DATASET: Final = "GLBX.MDP3"
DATABENTO_SCHEMA: Final = "mbp-1"
FIXED_PRICE_SCALE: Final = 1_000_000_000


@dataclass(frozen=True, slots=True)
class TapeSourceSpec:
    source_id: str
    provider: str
    market: str
    independent: bool
    credential_env: str | None
    implemented: bool

    @property
    def configured(self) -> bool:
        return (
            self.credential_env is None
            or bool(os.getenv(self.credential_env, "").strip())
        )


TAPE_SOURCE_SPECS: Final = {
    KRAKEN_TAPE_SOURCE_ID: TapeSourceSpec(
        source_id=KRAKEN_TAPE_SOURCE_ID,
        provider="Kraken public market data",
        market="spot_crypto",
        independent=True,
        credential_env=None,
        implemented=True,
    ),
    COINBASE_TAPE_SOURCE_ID: TapeSourceSpec(
        source_id=COINBASE_TAPE_SOURCE_ID,
        provider="Coinbase Exchange public market data",
        market="spot_crypto",
        independent=True,
        credential_env=None,
        implemented=True,
    ),
    BINANCE_US_TAPE_SOURCE_ID: TapeSourceSpec(
        source_id=BINANCE_US_TAPE_SOURCE_ID,
        provider="Binance.US public market data",
        market="spot_crypto",
        independent=True,
        credential_env=None,
        implemented=True,
    ),
    DATABENTO_GLBX_TAPE_SOURCE_ID: TapeSourceSpec(
        source_id=DATABENTO_GLBX_TAPE_SOURCE_ID,
        provider="Databento GLBX.MDP3",
        market="futures",
        independent=True,
        credential_env="DATABENTO_API_KEY",
        implemented=True,
    ),
}


def tape_source_status() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "source_id": spec.source_id,
            "provider": spec.provider,
            "market": spec.market,
            "independent": spec.independent,
            "implemented": spec.implemented,
            "configured": spec.configured,
            "state": (
                "READY"
                if spec.implemented and spec.configured
                else "CREDENTIAL_REQUIRED"
                if spec.implemented
                else "NOT_IMPLEMENTED"
            ),
        }
        for spec in TAPE_SOURCE_SPECS.values()
    )


def _positive(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _iso_timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _observation_id(
    *,
    asset_id: str,
    source_id: str,
    source_symbol: str,
    received_at_utc: datetime,
    bid: float | None,
    ask: float | None,
    last: float | None,
) -> str:
    payload = {
        "asset_id": asset_id,
        "source_id": source_id,
        "source_symbol": source_symbol,
        "received_at_utc": received_at_utc.isoformat(),
        "bid": bid,
        "ask": ask,
        "last": last,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _build_observation(
    *,
    asset_id: str,
    source_id: str,
    venue: str,
    source_symbol: str,
    contract_id: str | None,
    bid: float | None,
    ask: float | None,
    last: float | None,
    exchange_ts: datetime | None,
    received_at_utc: datetime,
    source_data_version: str,
    source_ref: str,
) -> TapeSourceObservation:
    if received_at_utc.tzinfo is None:
        raise ValueError("received_at_utc must be timezone-aware")
    aid = str(asset_id).strip().lower()
    if not aid:
        raise ValueError("asset_id is required")
    valid_book = bid is not None and ask is not None and bid <= ask
    mark = ((bid + ask) / 2.0) if valid_book else last
    quality = (
        TapeSourceQuality.HEALTHY
        if mark is not None and (bid is None or ask is None or bid <= ask)
        else TapeSourceQuality.INVALID
    )
    return TapeSourceObservation(
        observation_id=_observation_id(
            asset_id=aid,
            source_id=source_id,
            source_symbol=source_symbol,
            received_at_utc=received_at_utc,
            bid=bid,
            ask=ask,
            last=last,
        ),
        asset_id=aid,
        source_id=source_id,
        venue=venue,
        source_symbol=source_symbol,
        contract_id=contract_id,
        bid=bid,
        ask=ask,
        last=last,
        mark=mark,
        exchange_ts=exchange_ts,
        received_ts=received_at_utc.astimezone(UTC),
        age_ms=0,
        quality=quality,
        source_data_version=source_data_version,
        source_ref=source_ref,
    )


def parse_kraken_rest_ticker(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    source_symbol: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    if payload.get("error") not in (None, [], ()):
        return None
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return None
    book = next((value for value in result.values() if isinstance(value, Mapping)), None)
    if book is None:
        return None
    try:
        bid = _positive(book["b"][0])
        ask = _positive(book["a"][0])
        last = _positive(book["c"][0])
    except (KeyError, IndexError, TypeError):
        return None
    if bid is None or ask is None:
        return None
    return _build_observation(
        asset_id=asset_id,
        source_id=KRAKEN_TAPE_SOURCE_ID,
        venue="Kraken",
        source_symbol=source_symbol,
        contract_id=None,
        bid=bid,
        ask=ask,
        last=last,
        exchange_ts=None,
        received_at_utc=received_at_utc,
        source_data_version="kraken_rest_ticker_v1",
        source_ref=f"kraken:/0/public/Ticker:{source_symbol}",
    )


def parse_coinbase_exchange_ticker(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    if str(payload.get("type") or "") not in {"ticker", "ticker_batch"}:
        return None
    product_id = str(payload.get("product_id") or "").strip().upper()
    bid = _positive(payload.get("best_bid"))
    ask = _positive(payload.get("best_ask"))
    last = _positive(payload.get("price"))
    if not product_id or bid is None or ask is None:
        return None
    return _build_observation(
        asset_id=asset_id,
        source_id=COINBASE_TAPE_SOURCE_ID,
        venue="Coinbase Exchange",
        source_symbol=product_id,
        contract_id=None,
        bid=bid,
        ask=ask,
        last=last,
        exchange_ts=_iso_timestamp(payload.get("time")),
        received_at_utc=received_at_utc,
        source_data_version="coinbase_exchange_ticker_v1",
        source_ref=f"coinbase:exchange:websocket:ticker:{product_id}",
    )


def parse_binance_us_book_ticker(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    symbol = str(payload.get("symbol") or "").strip().upper()
    bid = _positive(payload.get("bidPrice"))
    ask = _positive(payload.get("askPrice"))
    if not symbol or bid is None or ask is None:
        return None
    return _build_observation(
        asset_id=asset_id,
        source_id=BINANCE_US_TAPE_SOURCE_ID,
        venue="Binance.US",
        source_symbol=symbol,
        contract_id=None,
        bid=bid,
        ask=ask,
        last=_positive(payload.get("lastPrice")),
        exchange_ts=None,
        received_at_utc=received_at_utc,
        source_data_version="binance_us_book_ticker_v1",
        source_ref=f"binance.us:/api/v3/ticker/bookTicker:{symbol}",
    )


def _databento_price(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    # Databento UNDEF_PRICE is INT64_MAX.
    if raw == 9_223_372_036_854_775_807:
        return None
    price = raw / FIXED_PRICE_SCALE
    return _positive(price)


def parse_databento_mbp1(
    record: object,
    *,
    asset_id: str,
    source_symbol: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    """Normalize one Databento GLBX MBP-1 record into Tape truth.

    Python DBN records expose top-of-book entries through levels[0]. Prices use
    Databento's fixed 1e-9 representation. The adapter never infers a futures roll;
    callers must supply the reviewed raw source symbol.
    """
    levels = getattr(record, "levels", None)
    if not levels:
        return None
    level = levels[0]
    bid = _databento_price(getattr(level, "bid_px", None))
    ask = _databento_price(getattr(level, "ask_px", None))
    if bid is None or ask is None:
        return None
    ts_event = getattr(record, "ts_event", None)
    exchange_ts = None
    if ts_event is not None:
        try:
            exchange_ts = datetime.fromtimestamp(int(ts_event) / 1_000_000_000, tz=UTC)
        except (TypeError, ValueError, OSError, OverflowError):
            return None
    instrument_id = getattr(record, "instrument_id", None)
    return _build_observation(
        asset_id=asset_id,
        source_id=DATABENTO_GLBX_TAPE_SOURCE_ID,
        venue="CME Globex",
        source_symbol=source_symbol,
        contract_id=None if instrument_id is None else str(int(instrument_id)),
        bid=bid,
        ask=ask,
        last=_databento_price(getattr(record, "price", None)),
        exchange_ts=exchange_ts,
        received_at_utc=received_at_utc,
        source_data_version="databento_glbx_mbp1_v1",
        source_ref=f"databento:{DATABENTO_GLBX_DATASET}:{source_symbol}:{DATABENTO_SCHEMA}",
    )


def configured_databento_api_key() -> str | None:
    value = os.getenv("DATABENTO_API_KEY", "").strip()
    return value or None
