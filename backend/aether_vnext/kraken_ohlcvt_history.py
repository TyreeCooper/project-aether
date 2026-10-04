"""Strict parser for Kraken downloadable historical OHLCVT CSV files.

Kraken documents historical OHLCVT rows as:
timestamp, open, high, low, close, volume, trades

The archive omits empty intervals rather than zero-filling them. AETHER preserves
those gaps exactly. Kraken's support article does not bind the timestamp unit in the
CSV row contract, so this parser deliberately requires the caller to provide the
reviewed unit instead of inferring it from magnitude.

This module performs no network I/O and creates no research evidence.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
import math
from typing import Final


KRAKEN_OHLCVT_SOURCE_ID: Final = "kraken_ohlcvt_archive"
KRAKEN_OHLCVT_FORMAT_VERSION: Final = "kraken_ohlcvt_csv_v1"
KRAKEN_OHLCVT_INTERVAL_MINUTES: Final = frozenset(
    {1, 5, 15, 30, 60, 240, 720, 1440}
)
SUPPORTED_ASSETS: Final = frozenset({"btc", "eth"})
SUPPORTED_TIMESTAMP_UNITS: Final = frozenset(
    {"unix_seconds", "unix_milliseconds"}
)
UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class KrakenHistoricalOHLCVTBar:
    asset_id: str
    interval_minutes: int
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    source_id: str
    source_data_version: str
    source_ref: str
    available_at_utc: datetime

    def __post_init__(self) -> None:
        if self.asset_id not in SUPPORTED_ASSETS:
            raise ValueError("unsupported AETHER Kraken historical asset")
        if self.interval_minutes not in KRAKEN_OHLCVT_INTERVAL_MINUTES:
            raise ValueError("unsupported Kraken OHLCVT interval")
        for name in (
            "bucket_open_utc",
            "bucket_close_utc",
            "available_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        expected_close = self.bucket_open_utc + timedelta(
            minutes=self.interval_minutes
        )
        if self.bucket_close_utc != expected_close:
            raise ValueError("Kraken OHLCVT bar close does not match interval")
        if self.available_at_utc < self.bucket_close_utc:
            raise ValueError("historical bar cannot be available before close")
        for name in ("source_id", "source_data_version", "source_ref"):
            value = getattr(self, name)
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        values = {
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Kraken OHLCVT numeric fields must be finite")
        if any(values[name] <= 0.0 for name in ("open", "high", "low", "close")):
            raise ValueError("Kraken OHLCVT prices must be positive")
        if values["volume"] < 0.0:
            raise ValueError("Kraken OHLCVT volume cannot be negative")
        if values["high"] < max(
            values["open"],
            values["close"],
            values["low"],
        ):
            raise ValueError("Kraken OHLCVT high is inconsistent")
        if values["low"] > min(
            values["open"],
            values["close"],
            values["high"],
        ):
            raise ValueError("Kraken OHLCVT low is inconsistent")
        if (
            not isinstance(self.trades, int)
            or isinstance(self.trades, bool)
            or self.trades < 0
        ):
            raise ValueError("Kraken OHLCVT trades must be a nonnegative integer")


def _timestamp_utc(raw: str, *, unit: str) -> datetime:
    value = str(raw).strip()
    if not value:
        raise ValueError("Kraken OHLCVT timestamp is required")
    try:
        numeric = float(value)
    except ValueError as exc:
        raise ValueError("Kraken OHLCVT timestamp must be numeric") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("Kraken OHLCVT timestamp must be finite and nonnegative")
    if unit == "unix_seconds":
        seconds = numeric
    elif unit == "unix_milliseconds":
        seconds = numeric / 1000.0
    else:
        raise ValueError("unsupported Kraken OHLCVT timestamp unit")
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Kraken OHLCVT timestamp is out of range") from exc


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Kraken OHLCVT {name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Kraken OHLCVT {name} must be finite and positive")
    return value


def _nonnegative_float(raw: str, name: str) -> float:
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Kraken OHLCVT {name} must be numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Kraken OHLCVT {name} must be finite and nonnegative")
    return value


def _nonnegative_int(raw: str, name: str) -> int:
    text = str(raw).strip()
    if not text:
        raise ValueError(f"Kraken OHLCVT {name} is required")
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"Kraken OHLCVT {name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"Kraken OHLCVT {name} cannot be negative")
    return value


def parse_kraken_ohlcvt_csv(
    raw_csv: str,
    *,
    asset_id: str,
    interval_minutes: int,
    timestamp_unit: str,
    source_data_version: str,
    source_ref: str,
) -> tuple[KrakenHistoricalOHLCVTBar, ...]:
    """Parse one headerless Kraken OHLCVT CSV without synthesizing gaps."""
    asset = str(asset_id).strip().lower()
    if asset not in SUPPORTED_ASSETS:
        raise ValueError("unsupported AETHER Kraken historical asset")
    interval = int(interval_minutes)
    if interval not in KRAKEN_OHLCVT_INTERVAL_MINUTES:
        raise ValueError("unsupported Kraken OHLCVT interval")
    unit = str(timestamp_unit).strip()
    if unit not in SUPPORTED_TIMESTAMP_UNITS:
        raise ValueError("unsupported Kraken OHLCVT timestamp unit")
    data_version = str(source_data_version).strip()
    ref = str(source_ref).strip()
    if not data_version:
        raise ValueError("source_data_version is required")
    if not ref:
        raise ValueError("source_ref is required")
    if not isinstance(raw_csv, str) or not raw_csv.strip():
        raise ValueError("Kraken OHLCVT CSV is empty")

    reader = csv.reader(StringIO(raw_csv))
    out: list[KrakenHistoricalOHLCVTBar] = []
    prior_open: datetime | None = None
    interval_seconds = interval * 60

    for row_number, row in enumerate(reader, start=1):
        if not row or all(not str(value).strip() for value in row):
            continue
        if len(row) != 7:
            raise ValueError(
                f"Kraken OHLCVT row {row_number} must contain exactly 7 columns"
            )
        if row_number == 1 and str(row[0]).strip().lower() == "timestamp":
            raise ValueError("Kraken OHLCVT archive CSV must not contain a header")

        opened = _timestamp_utc(row[0], unit=unit)
        epoch_seconds = opened.timestamp()
        remainder = epoch_seconds % interval_seconds
        if min(remainder, interval_seconds - remainder) > 1e-6:
            raise ValueError(
                f"Kraken OHLCVT row {row_number} timestamp is not interval-aligned"
            )
        if prior_open is not None and opened <= prior_open:
            raise ValueError(
                "Kraken OHLCVT rows must be strictly increasing without duplicates"
            )
        prior_open = opened

        open_ = _positive_float(row[1], "open")
        high = _positive_float(row[2], "high")
        low = _positive_float(row[3], "low")
        close = _positive_float(row[4], "close")
        volume = _nonnegative_float(row[5], "volume")
        trades = _nonnegative_int(row[6], "trades")
        closed = opened + timedelta(minutes=interval)

        out.append(
            KrakenHistoricalOHLCVTBar(
                asset_id=asset,
                interval_minutes=interval,
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                trades=trades,
                source_id=KRAKEN_OHLCVT_SOURCE_ID,
                source_data_version=data_version,
                source_ref=ref,
                # Source law permits only completed bars at decision time.
                available_at_utc=closed,
            )
        )

    if not out:
        raise ValueError("Kraken OHLCVT CSV contains no data rows")
    return tuple(out)


def research_manifest_bar_rows(
    bars: tuple[KrakenHistoricalOHLCVTBar, ...],
) -> list[dict[str, object]]:
    """Convert parsed Kraken bars to research_warehouse manifest rows."""
    if not bars:
        raise ValueError("at least one parsed Kraken OHLCVT bar is required")
    return [
        {
            "asset_id": row.asset_id,
            "interval_seconds": row.interval_minutes * 60,
            "bucket_open_utc": row.bucket_open_utc.isoformat(),
            "bucket_close_utc": row.bucket_close_utc.isoformat(),
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "source_id": row.source_id,
            "source_data_version": row.source_data_version,
            "source_ref": row.source_ref,
            "available_at_utc": row.available_at_utc.isoformat(),
        }
        for row in bars
    ]
