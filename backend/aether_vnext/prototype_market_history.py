"""Immutable prototype market-bar persistence.

This ledger is deliberately separate from the research warehouse. It can warm the
BTC/ETH prototype and support PAPER runtime decisions, but its rows do not satisfy
held-out or Phase 18 evidence requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Sequence

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


def _chunks(values: Sequence[str], size: int = 500) -> tuple[tuple[str, ...], ...]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    rows = tuple(values)
    return tuple(rows[start:start + size] for start in range(0, len(rows), size))


def persist_prototype_market_bars(
    conn: Connection,
    store: VNextStore,
    bars: tuple[PrototypeMarketBar, ...],
    *,
    ingested_at_utc: datetime,
) -> int:
    """Persist immutable bars with bounded bulk existence checks and inserts."""
    if ingested_at_utc.tzinfo is None:
        raise ValueError("ingested_at_utc must be timezone-aware")
    if not bars:
        return 0

    ordered = tuple(
        sorted(
            bars,
            key=lambda row: (
                row.asset_id,
                row.interval_seconds,
                row.bucket_open_utc,
            ),
        )
    )
    by_id = [(prototype_market_bar_id(bar), bar) for bar in ordered]
    table = store.tables["prototype_market_bars"]

    existing_ids: set[str] = set()
    for chunk in _chunks(tuple(bar_id for bar_id, _ in by_id)):
        existing_ids.update(
            str(row[0])
            for row in conn.execute(
                sa.select(table.c.bar_id).where(table.c.bar_id.in_(chunk))
            )
        )

    values = [
        {
            "bar_id": bar_id,
            "asset_id": bar.asset_id,
            "interval_seconds": bar.interval_seconds,
            "bucket_open_utc": bar.bucket_open_utc,
            "bucket_close_utc": bar.bucket_close_utc,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "trade_count": int(bar.trade_count),
            "source_id": bar.source_id,
            "source_ref": bar.source_ref,
            "available_at_utc": bar.available_at_utc,
            "ingested_at_utc": ingested_at_utc,
        }
        for bar_id, bar in by_id
        if bar_id not in existing_ids
    ]
    if values:
        conn.execute(table.insert(), values)
    return len(values)


def _restore_utc(value: datetime) -> datetime:
    """Normalize DB-driver timestamps to an aware UTC datetime.

    PostgreSQL preserves timezone awareness for TIMESTAMPTZ. SQLite test
    round-trips DateTime(timezone=True) as naive values, so tests and local
    tooling must restore the declared UTC contract explicitly.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _bar_from_row(row) -> PrototypeMarketBar:
    return PrototypeMarketBar(
        asset_id=str(row["asset_id"]),
        interval_seconds=int(row["interval_seconds"]),
        bucket_open_utc=_restore_utc(row["bucket_open_utc"]),
        bucket_close_utc=_restore_utc(row["bucket_close_utc"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        trade_count=int(row["trade_count"]),
        source_id=str(row["source_id"]),
        source_ref=str(row["source_ref"]),
        available_at_utc=_restore_utc(row["available_at_utc"]),
    )


def load_prototype_market_bars_for_assets(
    conn: Connection,
    store: VNextStore,
    *,
    asset_ids: Sequence[str],
    interval_seconds: int,
    end_at_utc: datetime,
    start_at_utc: datetime | None = None,
) -> dict[str, tuple[PrototypeMarketBar, ...]]:
    assets = tuple(
        dict.fromkeys(
            str(asset_id).strip().lower()
            for asset_id in asset_ids
            if str(asset_id).strip()
        )
    )
    if not assets:
        return {}
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if start_at_utc is not None and start_at_utc.tzinfo is None:
        raise ValueError("start_at_utc must be timezone-aware")

    table = store.tables["prototype_market_bars"]
    stmt = sa.select(table).where(
        table.c.asset_id.in_(assets),
        table.c.interval_seconds == int(interval_seconds),
        table.c.bucket_close_utc <= end_at_utc,
        table.c.available_at_utc <= end_at_utc,
    )
    if start_at_utc is not None:
        stmt = stmt.where(table.c.bucket_open_utc >= start_at_utc)

    grouped: dict[str, list[PrototypeMarketBar]] = {
        asset_id: [] for asset_id in assets
    }
    rows = conn.execute(
        stmt.order_by(
            table.c.asset_id.asc(),
            table.c.bucket_open_utc.asc(),
        )
    ).mappings()
    for row in rows:
        grouped[str(row["asset_id"])].append(_bar_from_row(row))
    return {
        asset_id: tuple(grouped[asset_id])
        for asset_id in assets
    }


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
    return load_prototype_market_bars_for_assets(
        conn,
        store,
        asset_ids=(asset,),
        interval_seconds=interval_seconds,
        end_at_utc=end_at_utc,
        start_at_utc=start_at_utc,
    )[asset]
