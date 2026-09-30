"""Immutable prototype market-bar persistence.

This ledger is deliberately separate from the research warehouse. It can warm the
BTC/ETH prototype and support PAPER runtime decisions, but its rows do not satisfy
held-out or Phase 18 evidence requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class PrototypeMarketBar:
    asset_id: str
    interval_seconds: int
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    source_id: str
    source_ref: str
    available_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.asset_id or self.asset_id != self.asset_id.strip().lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        for name in ("bucket_open_utc", "bucket_close_utc", "available_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.bucket_close_utc <= self.bucket_open_utc:
            raise ValueError("bar close must follow bar open")
        if self.available_at_utc < self.bucket_close_utc:
            raise ValueError("bar cannot be available before close")
        values = tuple(float(getattr(self, name)) for name in ("open","high","low","close","volume"))
        if any(not math.isfinite(value) for value in values):
            raise ValueError("bar numeric values must be finite")
        if any(float(getattr(self, name)) <= 0 for name in ("open","high","low","close")):
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is inconsistent")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is inconsistent")
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")
        if isinstance(self.trade_count, bool) or self.trade_count < 0:
            raise ValueError("trade_count must be a nonnegative integer")
        if not self.source_id.strip() or not self.source_ref.strip():
            raise ValueError("source identity is required")

    @property
    def interval(self) -> timedelta:
        return timedelta(seconds=self.interval_seconds)


def prototype_market_bar_id(bar: PrototypeMarketBar) -> str:
    payload = {
        "asset_id": bar.asset_id,
        "interval_seconds": bar.interval_seconds,
        "bucket_open_utc": bar.bucket_open_utc.isoformat(),
        "bucket_close_utc": bar.bucket_close_utc.isoformat(),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "trade_count": int(bar.trade_count),
        "source_id": bar.source_id,
        "source_ref": bar.source_ref,
        "available_at_utc": bar.available_at_utc.isoformat(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def persist_prototype_market_bars(
    conn: Connection,
    store: VNextStore,
    bars: tuple[PrototypeMarketBar, ...],
    *,
    ingested_at_utc: datetime,
) -> int:
    if ingested_at_utc.tzinfo is None:
        raise ValueError("ingested_at_utc must be timezone-aware")
    if not bars:
        return 0
    table = store.tables["prototype_market_bars"]
    inserted = 0
    for bar in sorted(bars, key=lambda row: (row.asset_id, row.interval_seconds, row.bucket_open_utc)):
        bar_id = prototype_market_bar_id(bar)
        existing = conn.execute(
            sa.select(table.c.bar_id).where(table.c.bar_id == bar_id)
        ).first()
        if existing is not None:
            continue
        conn.execute(
            table.insert().values(
                bar_id=bar_id,
                asset_id=bar.asset_id,
                interval_seconds=bar.interval_seconds,
                bucket_open_utc=bar.bucket_open_utc,
                bucket_close_utc=bar.bucket_close_utc,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
                trade_count=int(bar.trade_count),
                source_id=bar.source_id,
                source_ref=bar.source_ref,
                available_at_utc=bar.available_at_utc,
                ingested_at_utc=ingested_at_utc,
            )
        )
        inserted += 1
    return inserted


def load_prototype_market_bars(
    conn: Connection,
    store: VNextStore,
    *,
    asset_id: str,
    interval_seconds: int,
    end_at_utc: datetime,
    start_at_utc: datetime | None = None,
) -> tuple[PrototypeMarketBar, ...]:
    asset = str(asset_id).strip().lower()
    if not asset:
        raise ValueError("asset_id is required")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if start_at_utc is not None and start_at_utc.tzinfo is None:
        raise ValueError("start_at_utc must be timezone-aware")
    table = store.tables["prototype_market_bars"]
    stmt = sa.select(table).where(
        table.c.asset_id == asset,
        table.c.interval_seconds == int(interval_seconds),
        table.c.bucket_close_utc <= end_at_utc,
        table.c.available_at_utc <= end_at_utc,
    )
    if start_at_utc is not None:
        stmt = stmt.where(table.c.bucket_open_utc >= start_at_utc)
    rows = conn.execute(stmt.order_by(table.c.bucket_open_utc.asc())).mappings()
    return tuple(
        PrototypeMarketBar(
            asset_id=str(row["asset_id"]),
            interval_seconds=int(row["interval_seconds"]),
            bucket_open_utc=row["bucket_open_utc"],
            bucket_close_utc=row["bucket_close_utc"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            trade_count=int(row["trade_count"]),
            source_id=str(row["source_id"]),
            source_ref=str(row["source_ref"]),
            available_at_utc=row["available_at_utc"],
        )
        for row in rows
    )
