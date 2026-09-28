"""NinjaTrader/Tradovate market-data historical chart boundary for AETHER vNext.

The same market-data WebSocket protocol already used for DEMO quotes exposes
historical chart data through md/getChart. The provider response returns a
historicalId and realtimeId; chart events identify the subscription and carry
timestamped OHLC plus directional volume.

AETHER preserves the provider bar timestamp as provider_timestamp_utc and does not
assign research bucket-open/bucket-close semantics in this module. That normalization
remains blocked until the provider timestamp meaning is explicitly source-bound.

No order, position, account, or live-trading endpoint exists here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

from aether_vnext.ninjatrader_market import (
    NINJATRADER_MARKET_SOURCE_ID,
    encode_request,
    require_success_response,
)


NINJATRADER_HISTORY_ADAPTER_VERSION = (
    "ninjatrader_md_demo_chart_v1:raw_timestamp"
)
_FUTURES_ASSETS = frozenset({"mes", "mnq", "mgc", "mcl", "us10y"})
_UNDERLYING_TYPES = frozenset({"MinuteBar", "DailyBar"})
_ELEMENT_SIZE_UNIT = "UnderlyingUnits"


@dataclass(frozen=True, slots=True)
class NinjaTraderChartSubscription:
    historical_id: int
    realtime_id: int

    def __post_init__(self) -> None:
        if self.historical_id <= 0 or self.realtime_id <= 0:
            raise ValueError("NinjaTrader chart subscription IDs must be positive")
        if self.historical_id == self.realtime_id:
            raise ValueError(
                "historical_id and realtime_id must be distinct"
            )


@dataclass(frozen=True, slots=True)
class NinjaTraderHistoricalBar:
    asset_id: str
    current_contract: str
    contract_id: int
    historical_id: int
    provider_timestamp_utc: datetime
    trade_date: int | None
    open: float
    high: float
    low: float
    close: float
    up_volume: float
    down_volume: float
    source_id: str
    source_data_version: str
    source_ref: str
    fetched_at_utc: datetime

    def __post_init__(self) -> None:
        if self.asset_id not in _FUTURES_ASSETS:
            raise ValueError("unsupported AETHER NinjaTrader historical future")
        if not str(self.current_contract).strip():
            raise ValueError("current_contract is required")
        if isinstance(self.contract_id, bool) or self.contract_id <= 0:
            raise ValueError("contract_id must be positive")
        if self.historical_id <= 0:
            raise ValueError("historical_id must be positive")
        if self.provider_timestamp_utc.tzinfo is None:
            raise ValueError("provider_timestamp_utc must be timezone-aware")
        if self.fetched_at_utc.tzinfo is None:
            raise ValueError("fetched_at_utc must be timezone-aware")
        if self.provider_timestamp_utc > self.fetched_at_utc:
            raise ValueError(
                "NinjaTrader historical bar timestamp cannot be in the future"
            )
        if self.trade_date is not None:
            text = str(self.trade_date)
            if len(text) != 8 or not text.isdigit():
                raise ValueError("trade_date must use YYYYMMDD integer form")
        for name in ("source_id", "source_data_version", "source_ref"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        values = {
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "up_volume": float(self.up_volume),
            "down_volume": float(self.down_volume),
        }
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("NinjaTrader historical values must be finite")
        if any(values[name] <= 0 for name in ("open", "high", "low", "close")):
            raise ValueError("NinjaTrader historical prices must be positive")
        if values["up_volume"] < 0 or values["down_volume"] < 0:
            raise ValueError("NinjaTrader historical volume cannot be negative")
        if values["high"] < max(
            values["open"], values["close"], values["low"]
        ):
            raise ValueError("NinjaTrader historical high is inconsistent")
        if values["low"] > min(
            values["open"], values["close"], values["high"]
        ):
            raise ValueError("NinjaTrader historical low is inconsistent")

    @property
    def total_volume(self) -> float:
        return float(self.up_volume) + float(self.down_volume)


def _symbol(value: str | int) -> str | int:
    if isinstance(value, bool):
        raise ValueError("symbol must be a contract symbol or contract ID")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("contract ID must be positive")
        return value
    normalized = str(value).strip()
    if not normalized or "\n" in normalized:
        raise ValueError("contract symbol must be one nonblank line")
    return normalized


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("chart timestamp must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def get_chart_request(
    *,
    symbol: str | int,
    request_id: int,
    underlying_type: str,
    element_size: int,
    as_far_as_timestamp_utc: datetime | None = None,
    as_much_as_elements: int | None = None,
) -> str:
    """Encode one market-data-only historical chart request."""
    kind = str(underlying_type).strip()
    if kind not in _UNDERLYING_TYPES:
        raise ValueError("unsupported NinjaTrader chart underlying_type")
    if isinstance(element_size, bool) or int(element_size) <= 0:
        raise ValueError("element_size must be a positive integer")
    if (
        as_far_as_timestamp_utc is None
        and as_much_as_elements is None
    ):
        raise ValueError("NinjaTrader chart timeRange requires a bound")
    if (
        as_much_as_elements is not None
        and (
            isinstance(as_much_as_elements, bool)
            or int(as_much_as_elements) <= 0
        )
    ):
        raise ValueError("as_much_as_elements must be a positive integer")

    time_range: dict[str, object] = {}
    if as_far_as_timestamp_utc is not None:
        time_range["asFarAsTimestamp"] = _timestamp_text(
            as_far_as_timestamp_utc
        )
    if as_much_as_elements is not None:
        time_range["asMuchAsElements"] = int(as_much_as_elements)

    return encode_request(
        endpoint="md/getChart",
        request_id=request_id,
        body={
            "symbol": _symbol(symbol),
            "chartDescription": {
                "underlyingType": kind,
                "elementSize": int(element_size),
                "elementSizeUnit": _ELEMENT_SIZE_UNIT,
                "withHistogram": False,
            },
            "timeRange": time_range,
        },
    )


def cancel_chart_request(
    *,
    subscription_id: int,
    request_id: int,
) -> str:
    if isinstance(subscription_id, bool) or int(subscription_id) <= 0:
        raise ValueError("subscription_id must be positive")
    return encode_request(
        endpoint="md/cancelChart",
        request_id=request_id,
        body={"subscriptionId": int(subscription_id)},
    )


def chart_subscription_from_response(
    messages: tuple[dict[str, Any], ...],
    *,
    request_id: int,
) -> NinjaTraderChartSubscription:
    response = require_success_response(
        messages,
        request_id=request_id,
        operation="md/getChart",
    )
    data = response.get("d")
    if not isinstance(data, dict):
        raise ValueError("NinjaTrader getChart response data is missing")
    try:
        historical_id = int(data["historicalId"])
        realtime_id = int(data["realtimeId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "NinjaTrader getChart subscription IDs are invalid"
        ) from exc
    return NinjaTraderChartSubscription(
        historical_id=historical_id,
        realtime_id=realtime_id,
    )


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return parsed


def _provider_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "NinjaTrader historical timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(
            "NinjaTrader historical timestamp must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def parse_historical_chart_events(
    messages: tuple[dict[str, Any], ...],
    *,
    asset_id: str,
    current_contract: str,
    contract_id: int,
    historical_id: int,
    source_data_version: str,
    source_ref: str,
    fetched_at_utc: datetime,
) -> tuple[NinjaTraderHistoricalBar, ...]:
    """Parse only bars belonging to the requested historical subscription."""
    asset = str(asset_id).strip().lower()
    if asset not in _FUTURES_ASSETS:
        raise ValueError("unsupported AETHER NinjaTrader historical future")
    contract = str(current_contract).strip()
    if not contract:
        raise ValueError("current_contract is required")
    if isinstance(contract_id, bool) or int(contract_id) <= 0:
        raise ValueError("contract_id must be positive")
    if isinstance(historical_id, bool) or int(historical_id) <= 0:
        raise ValueError("historical_id must be positive")
    if fetched_at_utc.tzinfo is None:
        raise ValueError("fetched_at_utc must be timezone-aware")
    version = str(source_data_version).strip()
    ref = str(source_ref).strip()
    if not version or not ref:
        raise ValueError("source_data_version and source_ref are required")

    out: list[NinjaTraderHistoricalBar] = []
    prior_timestamp: datetime | None = None
    for message in messages:
        if message.get("e") != "chart":
            continue
        data = message.get("d")
        if not isinstance(data, dict):
            continue
        charts = data.get("charts")
        if not isinstance(charts, list):
            continue
        for chart in charts:
            if not isinstance(chart, dict):
                continue
            try:
                chart_id = int(chart.get("id"))
            except (TypeError, ValueError):
                continue
            if chart_id != int(historical_id):
                continue
            trade_date_raw = chart.get("td")
            trade_date = (
                None if trade_date_raw is None else int(trade_date_raw)
            )
            bars = chart.get("bars")
            if not isinstance(bars, list):
                continue
            for raw_bar in bars:
                if not isinstance(raw_bar, dict):
                    raise ValueError(
                        "NinjaTrader historical bar must be an object"
                    )
                timestamp = _provider_timestamp(
                    raw_bar.get("timestamp")
                )
                if (
                    prior_timestamp is not None
                    and timestamp <= prior_timestamp
                ):
                    raise ValueError(
                        "NinjaTrader historical timestamps must be strictly increasing"
                    )
                prior_timestamp = timestamp
                out.append(
                    NinjaTraderHistoricalBar(
                        asset_id=asset,
                        current_contract=contract,
                        contract_id=int(contract_id),
                        historical_id=int(historical_id),
                        provider_timestamp_utc=timestamp,
                        trade_date=trade_date,
                        open=_positive_number(raw_bar.get("open"), "open"),
                        high=_positive_number(raw_bar.get("high"), "high"),
                        low=_positive_number(raw_bar.get("low"), "low"),
                        close=_positive_number(raw_bar.get("close"), "close"),
                        up_volume=_nonnegative_number(
                            raw_bar.get("upVolume"),
                            "upVolume",
                        ),
                        down_volume=_nonnegative_number(
                            raw_bar.get("downVolume"),
                            "downVolume",
                        ),
                        source_id=NINJATRADER_MARKET_SOURCE_ID,
                        source_data_version=version,
                        source_ref=ref,
                        fetched_at_utc=fetched_at_utc,
                    )
                )
    return tuple(out)
