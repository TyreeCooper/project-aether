"""Public Coinbase Exchange candle transport for prototype warm-up comparison.

This source is NOT Kraken evidence and is NOT Phase-18 evidence. It exists only so
the PAPER prototype can evaluate whether a temporary cross-venue warm-up
source is technically usable while canonical Kraken market ingress remains the
execution-market authority.

No database mutation occurs in this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Final, Mapping, Sequence

import httpx

from aether_vnext.prototype_market_history import PrototypeMarketBar


UTC = timezone.utc
COINBASE_PRODUCTS_URL: Final = "https://api.exchange.coinbase.com/products"
COINBASE_CANDLES_BASE: Final = COINBASE_PRODUCTS_URL
COINBASE_SOURCE_ID: Final = "coinbase_exchange_public_candles"
COINBASE_PRODUCT: Final = {"btc": "BTC-USD", "eth": "ETH-USD"}
HOUR = timedelta(hours=1)
MAX_CANDLES_PER_REQUEST: Final = 300


def _asset(value: str) -> str:
    asset = str(value).strip().lower()
    if not asset:
        raise ValueError("asset_id is required")
    return asset


def _coinbase_product(asset: str, explicit: str | None) -> str:
    product = str(explicit or COINBASE_PRODUCT.get(asset) or "").strip().upper()
    if not product:
        raise ValueError(
            "dynamic Coinbase warm-up requires an explicit Coinbase product"
        )
    return product


def parse_coinbase_public_products(
    payload: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    """Index currently online public Coinbase products by provider-authored currencies."""
    if not isinstance(payload, Sequence):
        raise ValueError("Coinbase products response must be a sequence")
    out: dict[tuple[str, str], str] = {}
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise ValueError("Coinbase product row must be an object")
        product_id = str(raw.get("id") or "").strip().upper()
        base = str(raw.get("base_currency") or "").strip().upper()
        quote = str(raw.get("quote_currency") or "").strip().upper()
        status = str(raw.get("status") or "").strip().lower()
        disabled = raw.get("trading_disabled")
        if not product_id or not base or not quote:
            continue
        if status and status != "online":
            continue
        if disabled is True:
            continue
        key = (base, quote)
        prior = out.get(key)
        if prior is not None and prior != product_id:
            raise ValueError(
                f"duplicate Coinbase product identity for {base}/{quote}"
            )
        out[key] = product_id
    return out


async def fetch_coinbase_public_products(
    *,
    timeout_s: float = 20.0,
    client: httpx.AsyncClient | None = None,
) -> dict[tuple[str, str], str]:
    """Fetch the public Coinbase product catalog without guessing product IDs."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await http.get(
            COINBASE_PRODUCTS_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "project-aether-prototype-history-probe",
            },
        )
        response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Coinbase products response was not a list")
        return parse_coinbase_public_products(payload)
    finally:
        if owns_client:
            await http.aclose()


def _utc_epoch(value: object) -> datetime:
    if isinstance(value, bool):
        raise ValueError("Coinbase candle timestamp must be numeric")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coinbase candle timestamp must be an epoch integer") from exc
    if seconds < 0:
        raise ValueError("Coinbase candle timestamp cannot be negative")
    return datetime.fromtimestamp(seconds, tz=UTC)


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if number < 0:
        raise ValueError(f"{name} cannot be negative")
    return number


def parse_coinbase_hourly_candles(
    payload: Sequence[Sequence[object]],
    *,
    asset_id: str,
    end_at_utc: datetime,
    coinbase_product: str | None = None,
) -> tuple[PrototypeMarketBar, ...]:
    asset = _asset(asset_id)
    product = _coinbase_product(asset, coinbase_product)
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if not isinstance(payload, Sequence):
        raise ValueError("Coinbase candle response must be a sequence")

    rows: dict[datetime, PrototypeMarketBar] = {}
    for raw in payload:
        if not isinstance(raw, Sequence) or len(raw) < 6:
            raise ValueError("Coinbase candle row must contain six values")
        opened = _utc_epoch(raw[0])
        if int(opened.timestamp()) % 3600 != 0:
            raise ValueError("Coinbase hourly candle is not hour-aligned")
        closed = opened + HOUR
        if closed > end_at_utc:
            continue
        low = _positive(raw[1], "low")
        high = _positive(raw[2], "high")
        open_ = _positive(raw[3], "open")
        close = _positive(raw[4], "close")
        volume = _nonnegative(raw[5], "volume")
        if high < max(open_, close, low) or low > min(open_, close, high):
            raise ValueError("Coinbase OHLC geometry is inconsistent")
        if opened in rows:
            raise ValueError("duplicate Coinbase candle timestamp")
        rows[opened] = PrototypeMarketBar(
            asset_id=asset,
            interval_seconds=3600,
            bucket_open_utc=opened,
            bucket_close_utc=closed,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            trade_count=0,
            source_id=COINBASE_SOURCE_ID,
            source_ref=(
                f"coinbase-exchange:/products/{product}/candles:"
                "granularity=3600"
            ),
            available_at_utc=closed,
        )
    return tuple(rows[key] for key in sorted(rows))


def _floor_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("time must be timezone-aware")
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


async def fetch_coinbase_hourly_history(
    *,
    asset_id: str,
    end_at_utc: datetime,
    coinbase_product: str | None = None,
    minimum_bars: int = 2200,
    timeout_s: float = 20.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[PrototypeMarketBar, ...]:
    """Fetch completed hourly candles in <=300-candle windows.

    The Coinbase API documents a 300-candle maximum per request. Windows move
    backward without overlap and the result is deduplicated/content checked.
    """
    asset = _asset(asset_id)
    product = _coinbase_product(asset, coinbase_product)
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")

    end = _floor_hour(end_at_utc)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    by_open: dict[datetime, PrototypeMarketBar] = {}

    try:
        cursor_end = end
        max_windows = (minimum_bars // MAX_CANDLES_PER_REQUEST) + 5
        for _ in range(max_windows):
            cursor_start = cursor_end - timedelta(
                hours=MAX_CANDLES_PER_REQUEST
            )
            response = await http.get(
                f"{COINBASE_CANDLES_BASE}/{product}/candles",
                params={
                    "granularity": 3600,
                    "start": cursor_start.isoformat().replace("+00:00", "Z"),
                    "end": cursor_end.isoformat().replace("+00:00", "Z"),
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "project-aether-prototype-history-probe",
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
            if not isinstance(payload, list):
                raise RuntimeError("Coinbase candles response was not a list")
            rows = parse_coinbase_hourly_candles(
                payload,
                asset_id=asset,
                end_at_utc=end,
                coinbase_product=product,
            )
            for row in rows:
                existing = by_open.get(row.bucket_open_utc)
                if existing is not None and existing != row:
                    raise RuntimeError("Coinbase candle changed across windows")
                by_open[row.bucket_open_utc] = row

            if len(by_open) >= minimum_bars:
                break
            cursor_end = cursor_start

        ordered = tuple(by_open[key] for key in sorted(by_open))
        if len(ordered) < minimum_bars:
            raise RuntimeError(
                f"Coinbase warm-up returned {len(ordered)} bars; "
                f"{minimum_bars} required"
            )
        return ordered
    finally:
        if owns_client:
            await http.aclose()
