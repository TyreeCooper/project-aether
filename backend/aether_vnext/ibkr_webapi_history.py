"""Source-bound IBKR Web API historical OHLC response boundary.

Current IBKR Web API documentation binds:
- GET /v1/api/iserver/marketdata/history
- required conid, period, and bar
- optional exchange, outsideRth, startTime, direction, and source
- response OHLCV rows with fields o/h/l/c/v/t

AETHER deliberately does NOT normalize provider field t into research
bucket_open_utc/bucket_close_utc here because the current provider reference does not
explicitly state whether t denotes the bar open or bar close. The timestamp is
preserved exactly as provider_timestamp_utc. A later source-bound normalization step
must resolve that semantic before rows may enter the immutable PIT research warehouse.

This module performs no network I/O, authentication, account mutation, or trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Mapping


IBKR_HISTORY_ENDPOINT = "/v1/api/iserver/marketdata/history"
IBKR_HISTORY_SOURCE_ID = "ibkr_webapi_historical_market_data"
IBKR_HISTORY_ADAPTER_VERSION = "ibkr_webapi_history_v1:raw_timestamp"
IBKR_HISTORY_TIMESTAMP_UNIT = "epoch_milliseconds"

_EQUITY_ASSETS = frozenset({"nvda", "tsla", "pltr"})
_PERIOD_RE = re.compile(r"^[1-9][0-9]*(?:min|h|d|w|m|y)$")
_BAR_RE = re.compile(r"^[1-9][0-9]*(?:S|min|h|d|w|m)$")
_SOURCES = frozenset({"Last", "Bid_Ask", "Midpoint"})


@dataclass(frozen=True, slots=True)
class IbkrHistoricalRequest:
    contract_id: int
    period: str
    bar: str
    exchange: str | None = None
    outside_rth: bool = False
    start_time_utc: datetime | None = None
    direction: int | None = None
    source: str = "Last"

    def __post_init__(self) -> None:
        if isinstance(self.contract_id, bool) or int(self.contract_id) <= 0:
            raise ValueError("IBKR contract_id must be a positive integer")
        if not _PERIOD_RE.fullmatch(str(self.period).strip()):
            raise ValueError("IBKR historical period is invalid")
        if not _BAR_RE.fullmatch(str(self.bar).strip()):
            raise ValueError("IBKR historical bar is invalid")
        if self.exchange is not None and not str(self.exchange).strip():
            raise ValueError("IBKR exchange cannot be blank")
        if not isinstance(self.outside_rth, bool):
            raise ValueError("outside_rth must be boolean")
        if self.start_time_utc is not None and self.start_time_utc.tzinfo is None:
            raise ValueError("start_time_utc must be timezone-aware")
        if self.direction not in {None, -1, 1}:
            raise ValueError("IBKR historical direction must be -1, 1, or omitted")
        if self.start_time_utc is None and self.direction == -1:
            raise ValueError(
                "IBKR direction=-1 requires explicit start_time_utc"
            )
        if str(self.source).strip() not in _SOURCES:
            raise ValueError("unsupported IBKR historical source")

    def query_params(self) -> dict[str, object]:
        params: dict[str, object] = {
            "conid": int(self.contract_id),
            "period": str(self.period).strip(),
            "bar": str(self.bar).strip(),
            "outsideRth": bool(self.outside_rth),
            "source": str(self.source).strip(),
        }
        if self.exchange is not None:
            params["exchange"] = str(self.exchange).strip()
        if self.start_time_utc is not None:
            normalized = self.start_time_utc.astimezone(timezone.utc)
            params["startTime"] = normalized.strftime("%Y%m%d-%H:%M:%S")
        if self.direction is not None:
            params["direction"] = int(self.direction)
        return params


@dataclass(frozen=True, slots=True)
class IbkrHistoricalBar:
    asset_id: str
    contract_id: int
    provider_timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_id: str
    source_data_version: str
    source_ref: str
    fetched_at_utc: datetime

    def __post_init__(self) -> None:
        if self.asset_id not in _EQUITY_ASSETS:
            raise ValueError("unsupported AETHER IBKR historical equity")
        if isinstance(self.contract_id, bool) or self.contract_id <= 0:
            raise ValueError("IBKR contract_id must be a positive integer")
        if self.provider_timestamp_utc.tzinfo is None:
            raise ValueError("provider_timestamp_utc must be timezone-aware")
        if self.fetched_at_utc.tzinfo is None:
            raise ValueError("fetched_at_utc must be timezone-aware")
        if self.provider_timestamp_utc > self.fetched_at_utc:
            raise ValueError("IBKR historical bar timestamp cannot be in the future")
        for name in ("source_id", "source_data_version", "source_ref"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        values = {
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("IBKR historical OHLCV values must be finite")
        if any(values[name] <= 0 for name in ("open", "high", "low", "close")):
            raise ValueError("IBKR historical prices must be positive")
        if values["volume"] < 0:
            raise ValueError("IBKR historical volume cannot be negative")
        if values["high"] < max(
            values["open"], values["close"], values["low"]
        ):
            raise ValueError("IBKR historical high is inconsistent")
        if values["low"] > min(
            values["open"], values["close"], values["high"]
        ):
            raise ValueError("IBKR historical low is inconsistent")


@dataclass(frozen=True, slots=True)
class IbkrHistoricalBatch:
    asset_id: str
    contract_id: int
    symbol: str | None
    text: str | None
    requested_period: str
    requested_bar: str
    requested_source: str
    outside_rth: bool
    md_availability: str | None
    market_data_delay_ms: int | None
    reported_points: int | None
    price_factor: float | None
    volume_factor: float | None
    timestamp_unit: str
    bars: tuple[IbkrHistoricalBar, ...]


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"IBKR historical {name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"IBKR historical {name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"IBKR historical {name} must be finite")
    return number


def _optional_nonnegative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"IBKR historical {name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"IBKR historical {name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"IBKR historical {name} cannot be negative")
    return parsed


def _optional_positive_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    parsed = _finite_number(value, name)
    if parsed <= 0:
        raise ValueError(f"IBKR historical {name} must be positive")
    return parsed


def _provider_timestamp(value: object) -> datetime:
    if isinstance(value, bool):
        raise ValueError("IBKR historical t must be epoch milliseconds")
    try:
        milliseconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "IBKR historical t must be epoch milliseconds"
        ) from exc
    if milliseconds <= 0:
        raise ValueError("IBKR historical t must be positive")
    try:
        return datetime.fromtimestamp(
            milliseconds / 1000.0,
            tz=timezone.utc,
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("IBKR historical t is out of range") from exc


def parse_ibkr_history_response(
    payload: Mapping[str, object],
    *,
    asset_id: str,
    request: IbkrHistoricalRequest,
    source_data_version: str,
    source_ref: str,
    fetched_at_utc: datetime,
) -> IbkrHistoricalBatch:
    """Parse provider facts without assigning open/close timestamp semantics."""
    if not isinstance(payload, Mapping):
        raise ValueError("IBKR historical response must be a JSON object")
    asset = str(asset_id).strip().lower()
    if asset not in _EQUITY_ASSETS:
        raise ValueError("unsupported AETHER IBKR historical equity")
    if fetched_at_utc.tzinfo is None:
        raise ValueError("fetched_at_utc must be timezone-aware")
    version = str(source_data_version).strip()
    ref = str(source_ref).strip()
    if not version:
        raise ValueError("source_data_version is required")
    if not ref:
        raise ValueError("source_ref is required")

    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or not raw_data:
        raise ValueError("IBKR historical response data must be non-empty")

    rows: list[IbkrHistoricalBar] = []
    prior_ts: datetime | None = None
    for raw in raw_data:
        if not isinstance(raw, Mapping):
            raise ValueError("IBKR historical bar rows must be JSON objects")
        timestamp = _provider_timestamp(raw.get("t"))
        if prior_ts is not None and timestamp <= prior_ts:
            raise ValueError(
                "IBKR historical timestamps must be strictly increasing"
            )
        prior_ts = timestamp
        rows.append(
            IbkrHistoricalBar(
                asset_id=asset,
                contract_id=int(request.contract_id),
                provider_timestamp_utc=timestamp,
                open=_finite_number(raw.get("o"), "open"),
                high=_finite_number(raw.get("h"), "high"),
                low=_finite_number(raw.get("l"), "low"),
                close=_finite_number(raw.get("c"), "close"),
                volume=_finite_number(raw.get("v"), "volume"),
                source_id=IBKR_HISTORY_SOURCE_ID,
                source_data_version=version,
                source_ref=ref,
                fetched_at_utc=fetched_at_utc,
            )
        )

    return IbkrHistoricalBatch(
        asset_id=asset,
        contract_id=int(request.contract_id),
        symbol=(
            None
            if payload.get("symbol") is None
            else str(payload.get("symbol")).strip() or None
        ),
        text=(
            None
            if payload.get("text") is None
            else str(payload.get("text")).strip() or None
        ),
        requested_period=request.period,
        requested_bar=request.bar,
        requested_source=request.source,
        outside_rth=bool(payload.get("outsideRth", request.outside_rth)),
        md_availability=(
            None
            if payload.get("mdAvailability") is None
            else str(payload.get("mdAvailability")).strip() or None
        ),
        market_data_delay_ms=_optional_nonnegative_int(
            payload.get("mktDataDelay"),
            "mktDataDelay",
        ),
        reported_points=_optional_nonnegative_int(
            payload.get("points"),
            "points",
        ),
        price_factor=_optional_positive_number(
            payload.get("priceFactor"),
            "priceFactor",
        ),
        volume_factor=_optional_positive_number(
            payload.get("volumeFactor"),
            "volumeFactor",
        ),
        timestamp_unit=IBKR_HISTORY_TIMESTAMP_UNIT,
        bars=tuple(rows),
    )
