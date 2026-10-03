"""Concrete source adapters for the independent AETHER Consensus Tape.

Market-data sources are intentionally separate from execution providers. Public crypto
feeds can contribute without credentials. Databento GLBX is an independent,
credential-gated futures source; absence of its API key is reported as NOT_OBSERVED
and never replaced with synthetic market truth.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from typing import Any, Final, Mapping

import httpx

from aether_vnext.tape import TapeSourceObservation, TapeSourceQuality


UTC = timezone.utc
KRAKEN_TAPE_SOURCE_ID: Final = "kraken_public_tape"
COINBASE_TAPE_SOURCE_ID: Final = "coinbase_exchange_tape"
BINANCE_US_TAPE_SOURCE_ID: Final = "binance_us_tape"
GEMINI_TAPE_SOURCE_ID: Final = "gemini_public_tape"
DATABENTO_GLBX_TAPE_SOURCE_ID: Final = "databento_glbx_mbp1"

COINBASE_EXCHANGE_WS: Final = "wss://ws-feed.exchange.coinbase.com"
COINBASE_EXCHANGE_BOOK: Final = "https://api.exchange.coinbase.com/products/{product_id}/book"
KRAKEN_REST_TICKER: Final = "https://api.kraken.com/0/public/Ticker"
BINANCE_US_BOOK_TICKER: Final = "https://api.binance.us/api/v3/ticker/bookTicker"
GEMINI_PUBLIC_TICKER: Final = "https://api.gemini.com/v1/pubticker/{symbol}"
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
    GEMINI_TAPE_SOURCE_ID: TapeSourceSpec(
        source_id=GEMINI_TAPE_SOURCE_ID,
        provider="Gemini public market data",
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


def parse_coinbase_exchange_book(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    product_id: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        return None
    try:
        bid = _positive(bids[0][0])
        ask = _positive(asks[0][0])
    except (IndexError, TypeError):
        return None
    if bid is None or ask is None:
        return None
    product = str(product_id).strip().upper()
    if not product:
        return None
    return _build_observation(
        asset_id=asset_id,
        source_id=COINBASE_TAPE_SOURCE_ID,
        venue="Coinbase Exchange",
        source_symbol=product,
        contract_id=None,
        bid=bid,
        ask=ask,
        last=None,
        exchange_ts=None,
        received_at_utc=received_at_utc,
        source_data_version="coinbase_exchange_book_l1_v1",
        source_ref=f"coinbase:exchange:book:level1:{product}",
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


def parse_gemini_public_ticker(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    source_symbol: str,
    received_at_utc: datetime,
) -> TapeSourceObservation | None:
    bid = _positive(payload.get("bid"))
    ask = _positive(payload.get("ask"))
    last = _positive(payload.get("last"))
    symbol = str(source_symbol).strip().upper()
    if not symbol or bid is None or ask is None:
        return None
    return _build_observation(
        asset_id=asset_id,
        source_id=GEMINI_TAPE_SOURCE_ID,
        venue="Gemini",
        source_symbol=symbol,
        contract_id=None,
        bid=bid,
        ask=ask,
        last=last,
        exchange_ts=None,
        received_at_utc=received_at_utc,
        source_data_version="gemini_pubticker_v1",
        source_ref=f"gemini:/v1/pubticker/{symbol.lower()}",
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


@dataclass(frozen=True, slots=True)
class TapeFetchResult:
    observations: tuple[TapeSourceObservation, ...]
    failures: dict[str, str]


async def fetch_public_crypto_tape(
    *,
    asset_id: str,
    base_symbol: str,
    kraken_pair: str,
    timeout_s: float = 6.0,
) -> TapeFetchResult:
    """Fetch three independent public BBO lanes without coupling their failures."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    base = str(base_symbol).strip().upper()
    pair = str(kraken_pair).strip().upper()
    if not base or not pair:
        raise ValueError("base_symbol and kraken_pair are required")
    coinbase_product = f"{base}-USD"
    binance_symbol = f"{base}USD"
    gemini_symbol = f"{base}USD"

    async def kraken():
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(KRAKEN_REST_TICKER, params={"pair": pair})
            response.raise_for_status()
            now = datetime.now(UTC)
            row = parse_kraken_rest_ticker(
                response.json(),
                asset_id=asset_id,
                source_symbol=pair,
                received_at_utc=now,
            )
            if row is None:
                raise RuntimeError("kraken_ticker_unavailable")
            return row

    async def coinbase():
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(
                COINBASE_EXCHANGE_BOOK.format(product_id=coinbase_product),
                params={"level": 1},
            )
            response.raise_for_status()
            now = datetime.now(UTC)
            row = parse_coinbase_exchange_book(
                response.json(),
                asset_id=asset_id,
                product_id=coinbase_product,
                received_at_utc=now,
            )
            if row is None:
                raise RuntimeError("coinbase_book_unavailable")
            return row

    async def binance():
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(
                BINANCE_US_BOOK_TICKER,
                params={"symbol": binance_symbol},
            )
            response.raise_for_status()
            now = datetime.now(UTC)
            row = parse_binance_us_book_ticker(
                response.json(),
                asset_id=asset_id,
                received_at_utc=now,
            )
            if row is None:
                raise RuntimeError("binance_us_book_unavailable")
            return row

    async def gemini():
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(
                GEMINI_PUBLIC_TICKER.format(symbol=gemini_symbol.lower()),
            )
            response.raise_for_status()
            now = datetime.now(UTC)
            row = parse_gemini_public_ticker(
                response.json(),
                asset_id=asset_id,
                source_symbol=gemini_symbol,
                received_at_utc=now,
            )
            if row is None:
                raise RuntimeError("gemini_ticker_unavailable")
            return row

    fetches = (
        (KRAKEN_TAPE_SOURCE_ID, kraken()),
        (COINBASE_TAPE_SOURCE_ID, coinbase()),
        (BINANCE_US_TAPE_SOURCE_ID, binance()),
        (GEMINI_TAPE_SOURCE_ID, gemini()),
    )
    results = await asyncio.gather(
        *(coroutine for _, coroutine in fetches),
        return_exceptions=True,
    )
    observations: list[TapeSourceObservation] = []
    failures: dict[str, str] = {}
    for (source_id, _), result in zip(fetches, results):
        if isinstance(result, BaseException):
            failures[source_id] = f"{type(result).__name__}:{result}"
        else:
            observations.append(result)
    return TapeFetchResult(
        observations=tuple(sorted(observations, key=lambda row: row.source_id)),
        failures=dict(sorted(failures.items())),
    )


async def fetch_databento_glbx_mbp1(
    *,
    asset_id: str,
    source_symbol: str,
    timeout_s: float = 6.0,
) -> TapeSourceObservation:
    """Fetch one credentialed CME Globex BBO snapshot through Databento Live.

    This is deliberately one source lane, not a broker route. Missing credentials
    fail explicitly and cannot be replaced by NinjaTrader/IBKR execution state.
    """
    key = configured_databento_api_key()
    if key is None:
        raise RuntimeError("databento_api_key_missing")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    symbol = str(source_symbol).strip().upper()
    if not symbol:
        raise ValueError("source_symbol is required")

    def run_sync() -> TapeSourceObservation:
        import databento as db

        result: list[TapeSourceObservation] = []
        error: list[BaseException] = []
        done = __import__("threading").Event()
        client = db.Live(key=key)

        def on_record(record) -> None:
            if result or error:
                return
            try:
                row = parse_databento_mbp1(
                    record,
                    asset_id=asset_id,
                    source_symbol=symbol,
                    received_at_utc=datetime.now(UTC),
                )
                if row is not None:
                    result.append(row)
                    done.set()
            except BaseException as exc:
                error.append(exc)
                done.set()

        def on_error(exc: Exception) -> None:
            error.append(exc)
            done.set()

        client.subscribe(
            dataset=DATABENTO_GLBX_DATASET,
            schema=DATABENTO_SCHEMA,
            symbols=symbol,
            stype_in="raw_symbol",
        )
        client.add_callback(
            record_callback=on_record,
            exception_callback=on_error,
        )
        client.start()
        try:
            if not done.wait(timeout_s):
                raise TimeoutError("databento_mbp1_snapshot_timeout")
        finally:
            client.stop()
            client.block_for_close(timeout=2.0)
        if error:
            raise RuntimeError(
                f"databento_live_error:{type(error[0]).__name__}:{error[0]}"
            )
        if not result:
            raise RuntimeError("databento_mbp1_not_observed")
        return result[0]

    return await asyncio.to_thread(run_sync)
