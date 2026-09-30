"""Prototype-only BTC/ETH historical warm-up transports.

Two deliberately separated sources are supported:
- hourly: CryptoCompare's historical endpoint explicitly scoped to exchange=Kraken
  with conversion disabled. This is a temporary prototype warm-up source and is
  never represented as direct Kraken evidence.
- daily: Kraken's public REST OHLC endpoint, used only for completed daily bars.

These transports create PrototypeMarketBar rows only. They do not create held-out
research evidence, Product Registry bindings, setups, tickets, fills, or live orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Final, Mapping, Sequence

import httpx

from aether_vnext.prototype_market_history import PrototypeMarketBar


UTC = timezone.utc
CRYPTOCOMPARE_HISTOHOUR_URL: Final = (
    "https://min-api.cryptocompare.com/data/v2/histohour"
)
KRAKEN_REST_OHLC_URL: Final = "https://api.kraken.com/0/public/OHLC"
CRYPTOCOMPARE_SOURCE_ID: Final = "cryptocompare_kraken_histohour"
KRAKEN_DAILY_SOURCE_ID: Final = "kraken_public_rest_ohlc"
ASSET_SYMBOL: Final = {"btc": "BTC", "eth": "ETH"}
KRAKEN_PAIR: Final = {"btc": "XBTUSD", "eth": "ETHUSD"}
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _asset(value: str) -> str:
    asset = str(value).strip().lower()
    if asset not in ASSET_SYMBOL:
        raise ValueError("prototype historical warm-up supports btc/eth only")
    return asset


def _aware_utc_from_epoch(value: object) -> datetime:
    if isinstance(value, bool):
        raise ValueError("historical timestamp must be numeric")
    try:
        timestamp = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("historical timestamp must be an integer epoch") from exc
    if timestamp < 0:
        raise ValueError("historical timestamp cannot be negative")
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _nonnegative_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if numeric < 0:
        raise ValueError(f"{name} cannot be negative")
    return numeric


def parse_cryptocompare_kraken_hourly_payload(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    end_at_utc: datetime,
) -> tuple[PrototypeMarketBar, ...]:
    """Parse one CryptoCompare single-exchange hourly response.

    Zero-price placeholder rows are treated as absent intervals, never synthesized.
    """
    asset = _asset(asset_id)
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if str(payload.get("Response") or "") != "Success":
        message = str(payload.get("Message") or "historical provider response failed")
        raise RuntimeError(message)

    envelope = payload.get("Data")
    if not isinstance(envelope, Mapping):
        raise ValueError("CryptoCompare Data envelope is missing")
    raw_rows = envelope.get("Data")
    if not isinstance(raw_rows, Sequence):
        raise ValueError("CryptoCompare hourly rows are missing")

    source_ref = (
        f"cryptocompare:/data/v2/histohour:"
        f"e=Kraken:{ASSET_SYMBOL[asset]}/USD:tryConversion=false"
    )
    out: list[PrototypeMarketBar] = []
    seen: set[datetime] = set()

    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ValueError("CryptoCompare hourly row must be an object")
        opened = _aware_utc_from_epoch(raw.get("time"))
        closed = opened + HOUR
        if closed > end_at_utc:
            continue

        raw_prices = tuple(raw.get(name) for name in ("open", "high", "low", "close"))
        try:
            prices = tuple(float(value) for value in raw_prices)
        except (TypeError, ValueError) as exc:
            raise ValueError("CryptoCompare OHLC values must be numeric") from exc

        if all(value == 0.0 for value in prices):
            continue
        open_, high, low, close = (
            _positive_float(raw.get("open"), "open"),
            _positive_float(raw.get("high"), "high"),
            _positive_float(raw.get("low"), "low"),
            _positive_float(raw.get("close"), "close"),
        )
        if opened in seen:
            raise ValueError("duplicate CryptoCompare hourly timestamp")
        seen.add(opened)

        out.append(
            PrototypeMarketBar(
                asset_id=asset,
                interval_seconds=3600,
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=_nonnegative_float(
                    raw.get("volumefrom", 0.0),
                    "volumefrom",
                ),
                # Provider history does not expose Kraken trade count here.
                trade_count=0,
                source_id=CRYPTOCOMPARE_SOURCE_ID,
                source_ref=source_ref,
                available_at_utc=closed,
            )
        )

    return tuple(sorted(out, key=lambda row: row.bucket_open_utc))


def parse_kraken_completed_daily_payload(
    payload: Mapping[str, Any],
    *,
    asset_id: str,
    end_at_utc: datetime,
) -> tuple[PrototypeMarketBar, ...]:
    """Parse completed daily bars from Kraken REST.

    Kraken documents the final OHLC entry as the current not-yet-committed interval,
    so the final provider row is always excluded.
    """
    asset = _asset(asset_id)
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    errors = payload.get("error")
    if errors not in (None, [], ()):
        raise RuntimeError(f"Kraken OHLC error: {errors}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Kraken OHLC result is missing")

    series = next(
        (
            value
            for key, value in result.items()
            if key != "last" and isinstance(value, Sequence)
        ),
        None,
    )
    if series is None:
        raise ValueError("Kraken OHLC series is missing")

    source_ref = (
        f"kraken:/0/public/OHLC:pair={KRAKEN_PAIR[asset]}:"
        "interval=1440:completed-only"
    )
    out: list[PrototypeMarketBar] = []
    for raw in tuple(series)[:-1]:
        if not isinstance(raw, Sequence) or len(raw) < 8:
            raise ValueError("Kraken OHLC row must contain at least 8 values")
        opened = _aware_utc_from_epoch(raw[0])
        closed = opened + DAY
        if closed > end_at_utc:
            continue
        try:
            trades = int(raw[7])
        except (TypeError, ValueError) as exc:
            raise ValueError("Kraken OHLC trade count must be an integer") from exc
        if trades < 0:
            raise ValueError("Kraken OHLC trade count cannot be negative")

        out.append(
            PrototypeMarketBar(
                asset_id=asset,
                interval_seconds=86400,
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=_positive_float(raw[1], "open"),
                high=_positive_float(raw[2], "high"),
                low=_positive_float(raw[3], "low"),
                close=_positive_float(raw[4], "close"),
                volume=_nonnegative_float(raw[6], "volume"),
                trade_count=trades,
                source_id=KRAKEN_DAILY_SOURCE_ID,
                source_ref=source_ref,
                available_at_utc=closed,
            )
        )
    return tuple(out)


async def fetch_cryptocompare_kraken_hourly(
    *,
    asset_id: str,
    end_at_utc: datetime,
    minimum_bars: int = 2200,
    timeout_s: float = 20.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[PrototypeMarketBar, ...]:
    """Fetch enough exchange=Kraken hourly rows for the 90-day RV14 warm-up.

    CryptoCompare limits hourly history to 2000 points per request. Pagination walks
    backward using toTs. Conversion is disabled so a missing direct market fails
    rather than silently routing through another symbol.
    """
    asset = _asset(asset_id)
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        by_open: dict[datetime, PrototypeMarketBar] = {}
        to_ts = int(end_at_utc.timestamp())
        for _ in range(8):
            remaining = max(1, minimum_bars - len(by_open))
            limit = min(2000, remaining + 2)
            response = await http.get(
                CRYPTOCOMPARE_HISTOHOUR_URL,
                params={
                    "fsym": ASSET_SYMBOL[asset],
                    "tsym": "USD",
                    "limit": limit,
                    "aggregate": 1,
                    "toTs": to_ts,
                    "e": "Kraken",
                    "tryConversion": "false",
                    "extraParams": "project-aether-prototype",
                },
            )
            response.raise_for_status()
            rows = parse_cryptocompare_kraken_hourly_payload(
                response.json(),
                asset_id=asset,
                end_at_utc=end_at_utc,
            )
            if not rows:
                break
            for row in rows:
                by_open[row.bucket_open_utc] = row
            if len(by_open) >= minimum_bars:
                break
            earliest = min(row.bucket_open_utc for row in rows)
            next_to_ts = int(earliest.timestamp()) - 1
            if next_to_ts >= to_ts:
                raise RuntimeError("historical pagination did not move backward")
            to_ts = next_to_ts

        ordered = tuple(by_open[key] for key in sorted(by_open))
        if len(ordered) < minimum_bars:
            raise RuntimeError(
                f"historical warm-up returned {len(ordered)} bars; "
                f"{minimum_bars} required"
            )
        return ordered
    finally:
        if owns_client:
            await http.aclose()


async def fetch_kraken_completed_daily(
    *,
    asset_id: str,
    end_at_utc: datetime,
    timeout_s: float = 20.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[PrototypeMarketBar, ...]:
    asset = _asset(asset_id)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await http.get(
            KRAKEN_REST_OHLC_URL,
            params={
                "pair": KRAKEN_PAIR[asset],
                "interval": 1440,
                "assetVersion": 1,
            },
        )
        response.raise_for_status()
        return parse_kraken_completed_daily_payload(
            response.json(),
            asset_id=asset,
            end_at_utc=end_at_utc,
        )
    finally:
        if owns_client:
            await http.aclose()
