"""Immutable point-in-time research-bar warehouse for AETHER vNext.

This module accepts reviewed real completed OHLCV bars and binds them to one
ResearchDatasetSnapshot. It never downloads data, fills missing buckets, repairs
prices, creates synthetic bars, or produces strategy evidence.

Dataset identity is content-addressed: the declared ResearchDatasetSnapshot
content_hash must exactly match the normalized snapshot metadata and immutable bar
payload. Any mismatch is rejected before database mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.research import ResearchDatasetSnapshot
from aether_vnext.store import VNextStore


RESEARCH_BAR_MANIFEST_VERSION = "aether-vnext-research-bars-v1"


@dataclass(frozen=True, slots=True)
class ResearchBarRecord:
    research_bar_id: str
    dataset_snapshot_id: str
    asset_id: str
    interval_seconds: int
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_id: str
    source_data_version: str
    source_ref: str
    available_at_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "research_bar_id",
            "dataset_snapshot_id",
            "asset_id",
            "source_id",
            "source_data_version",
            "source_ref",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if (
            not isinstance(self.interval_seconds, int)
            or isinstance(self.interval_seconds, bool)
            or self.interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a positive integer")
        for name in (
            "bucket_open_utc",
            "bucket_close_utc",
            "available_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.bucket_close_utc <= self.bucket_open_utc:
            raise ValueError("research bar must close after bucket open")
        if self.available_at_utc < self.bucket_close_utc:
            raise ValueError(
                "research bar cannot be available before bucket close"
            )

        values = {
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("research bar prices/volume must be finite")
        if any(values[name] <= 0.0 for name in ("open", "high", "low", "close")):
            raise ValueError("research bar prices must be positive")
        if values["volume"] < 0.0:
            raise ValueError("research bar volume cannot be negative")
        if values["high"] < max(
            values["open"],
            values["close"],
            values["low"],
        ):
            raise ValueError("research bar high is inconsistent")
        if values["low"] > min(
            values["open"],
            values["close"],
            values["high"],
        ):
            raise ValueError("research bar low is inconsistent")


@dataclass(frozen=True, slots=True)
class ResearchBarManifest:
    manifest_version: str
    source_ref: str
    snapshot: ResearchDatasetSnapshot
    bars: tuple[ResearchBarRecord, ...]


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    rows = tuple(_text(row, name) for row in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} cannot contain duplicates")
    return rows


def _canonical_bar_payload(
    *,
    dataset_snapshot_id: str,
    asset_id: str,
    interval_seconds: int,
    bucket_open_utc: datetime,
    bucket_close_utc: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    source_id: str,
    source_data_version: str,
    source_ref: str,
    available_at_utc: datetime,
) -> dict[str, object]:
    return {
        "dataset_snapshot_id": dataset_snapshot_id,
        "asset_id": asset_id,
        "interval_seconds": interval_seconds,
        "bucket_open_utc": bucket_open_utc.isoformat(),
        "bucket_close_utc": bucket_close_utc.isoformat(),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "source_id": source_id,
        "source_data_version": source_data_version,
        "source_ref": source_ref,
        "available_at_utc": available_at_utc.isoformat(),
    }


def _hash_payload(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def research_bar_id(payload: Mapping[str, object]) -> str:
    return _hash_payload(dict(payload))


def research_dataset_content_hash(
    snapshot: ResearchDatasetSnapshot,
    bars: tuple[ResearchBarRecord, ...],
) -> str:
    """Hash immutable dataset metadata plus normalized bar content.

    snapshot.content_hash is intentionally excluded to avoid circular identity.
    """
    rows = tuple(
        sorted(
            bars,
            key=lambda row: (
                row.asset_id,
                row.interval_seconds,
                row.bucket_open_utc,
                row.bucket_close_utc,
                row.source_id,
                row.research_bar_id,
            ),
        )
    )
    return _hash_payload(
        {
            "dataset_snapshot": {
                "dataset_snapshot_id": snapshot.dataset_snapshot_id,
                "created_at_utc": snapshot.created_at_utc.isoformat(),
                "as_of_utc": snapshot.as_of_utc.isoformat(),
                "start_at_utc": snapshot.start_at_utc.isoformat(),
                "end_at_utc": snapshot.end_at_utc.isoformat(),
                "asset_ids": sorted(snapshot.asset_ids),
                "data_version": snapshot.data_version,
                "source_registry_version": snapshot.source_registry_version,
                "product_registry_version": snapshot.product_registry_version,
                "calendar_version": snapshot.calendar_version,
                "pit": snapshot.pit,
                "missing_data_policy": snapshot.missing_data_policy,
            },
            "bars": [
                _canonical_bar_payload(
                    dataset_snapshot_id=row.dataset_snapshot_id,
                    asset_id=row.asset_id,
                    interval_seconds=row.interval_seconds,
                    bucket_open_utc=row.bucket_open_utc,
                    bucket_close_utc=row.bucket_close_utc,
                    open_=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    source_id=row.source_id,
                    source_data_version=row.source_data_version,
                    source_ref=row.source_ref,
                    available_at_utc=row.available_at_utc,
                )
                for row in rows
            ],
        }
    )


def parse_research_bar_manifest(
    payload: Mapping[str, object],
) -> ResearchBarManifest:
    if not isinstance(payload, Mapping):
        raise ValueError("research bar manifest must be a JSON object")
    version = _text(payload.get("manifest_version"), "manifest_version")
    if version != RESEARCH_BAR_MANIFEST_VERSION:
        raise ValueError("unsupported research bar manifest_version")
    source_ref = _text(payload.get("source_ref"), "source_ref")

    raw_snapshot = payload.get("snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raise ValueError("snapshot must be a JSON object")
    asset_ids = _strings(raw_snapshot.get("asset_ids"), "asset_ids")
    if any(asset != asset.lower() for asset in asset_ids):
        raise ValueError("asset_ids must contain canonical lowercase IDs")

    declared_hash = _text(
        raw_snapshot.get("content_hash"),
        "content_hash",
    )
    if len(declared_hash) != 64 or any(
        ch not in "0123456789abcdef" for ch in declared_hash
    ):
        raise ValueError("content_hash must be a lowercase 64-hex digest")

    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=_text(
            raw_snapshot.get("dataset_snapshot_id"),
            "dataset_snapshot_id",
        ),
        created_at_utc=_utc(
            raw_snapshot.get("created_at_utc"),
            "created_at_utc",
        ),
        as_of_utc=_utc(raw_snapshot.get("as_of_utc"), "as_of_utc"),
        start_at_utc=_utc(
            raw_snapshot.get("start_at_utc"),
            "start_at_utc",
        ),
        end_at_utc=_utc(
            raw_snapshot.get("end_at_utc"),
            "end_at_utc",
        ),
        asset_ids=asset_ids,
        data_version=_text(
            raw_snapshot.get("data_version"),
            "data_version",
        ),
        source_registry_version=_text(
            raw_snapshot.get("source_registry_version"),
            "source_registry_version",
        ),
        product_registry_version=_text(
            raw_snapshot.get("product_registry_version"),
            "product_registry_version",
        ),
        calendar_version=_text(
            raw_snapshot.get("calendar_version"),
            "calendar_version",
        ),
        pit=raw_snapshot.get("pit") is True,
        missing_data_policy=_text(
            raw_snapshot.get("missing_data_policy"),
            "missing_data_policy",
        ),
        content_hash=declared_hash,
    )

    raw_bars = payload.get("bars")
    if not isinstance(raw_bars, list) or not raw_bars:
        raise ValueError("bars must be a non-empty list")

    bars: list[ResearchBarRecord] = []
    for raw_bar in raw_bars:
        if not isinstance(raw_bar, Mapping):
            raise ValueError("bar entries must be JSON objects")
        asset_id = _text(raw_bar.get("asset_id"), "asset_id")
        interval_raw = raw_bar.get("interval_seconds")
        if isinstance(interval_raw, bool):
            raise ValueError("interval_seconds must be a positive integer")
        try:
            interval_seconds = int(interval_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "interval_seconds must be a positive integer"
            ) from exc
        opened = _utc(raw_bar.get("bucket_open_utc"), "bucket_open_utc")
        closed = _utc(raw_bar.get("bucket_close_utc"), "bucket_close_utc")
        available = _utc(
            raw_bar.get("available_at_utc"),
            "available_at_utc",
        )
        source_id = _text(raw_bar.get("source_id"), "source_id")
        source_data_version = _text(
            raw_bar.get("source_data_version"),
            "source_data_version",
        )
        bar_source_ref = _text(
            raw_bar.get("source_ref", source_ref),
            "source_ref",
        )
        try:
            open_ = float(raw_bar.get("open"))
            high = float(raw_bar.get("high"))
            low = float(raw_bar.get("low"))
            close = float(raw_bar.get("close"))
            volume = float(raw_bar.get("volume"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "bar OHLCV fields must be numeric"
            ) from exc

        canonical = _canonical_bar_payload(
            dataset_snapshot_id=snapshot.dataset_snapshot_id,
            asset_id=asset_id,
            interval_seconds=interval_seconds,
            bucket_open_utc=opened,
            bucket_close_utc=closed,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source_id=source_id,
            source_data_version=source_data_version,
            source_ref=bar_source_ref,
            available_at_utc=available,
        )
        bars.append(
            ResearchBarRecord(
                research_bar_id=research_bar_id(canonical),
                dataset_snapshot_id=snapshot.dataset_snapshot_id,
                asset_id=asset_id,
                interval_seconds=interval_seconds,
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source_id=source_id,
                source_data_version=source_data_version,
                source_ref=bar_source_ref,
                available_at_utc=available,
            )
        )

    manifest = ResearchBarManifest(
        manifest_version=version,
        source_ref=source_ref,
        snapshot=snapshot,
        bars=tuple(bars),
    )
    validate_research_bar_manifest(manifest)
    actual_hash = research_dataset_content_hash(snapshot, manifest.bars)
    if actual_hash != snapshot.content_hash:
        raise ValueError(
            "research dataset content_hash does not match normalized bar content"
        )
    return manifest


def validate_research_bar_manifest(
    manifest: ResearchBarManifest,
) -> dict[str, object]:
    snapshot = manifest.snapshot
    keys: set[tuple[str, int, datetime]] = set()
    ids: set[str] = set()
    by_asset: dict[str, int] = {}

    for bar in manifest.bars:
        if bar.dataset_snapshot_id != snapshot.dataset_snapshot_id:
            raise ValueError("research bar dataset_snapshot_id mismatch")
        if bar.asset_id not in snapshot.asset_ids:
            raise ValueError("research bar asset absent from dataset snapshot")
        if bar.bucket_open_utc < snapshot.start_at_utc:
            raise ValueError("research bar starts before dataset snapshot")
        if bar.bucket_close_utc > snapshot.end_at_utc:
            raise ValueError("research bar ends after dataset snapshot")
        if bar.available_at_utc > snapshot.as_of_utc:
            raise ValueError("research bar was unavailable at dataset as_of_utc")

        key = (
            bar.asset_id,
            bar.interval_seconds,
            bar.bucket_open_utc,
        )
        if key in keys:
            raise ValueError(
                "duplicate research bar asset/interval/bucket_open"
            )
        keys.add(key)
        if bar.research_bar_id in ids:
            raise ValueError("duplicate research_bar_id")
        ids.add(bar.research_bar_id)
        by_asset[bar.asset_id] = by_asset.get(bar.asset_id, 0) + 1

    missing_assets = tuple(
        sorted(set(snapshot.asset_ids) - set(by_asset))
    )
    if missing_assets:
        raise ValueError(
            "dataset snapshot declares assets with no bars: "
            + ",".join(missing_assets)
        )

    return {
        "manifest_version": manifest.manifest_version,
        "dataset_snapshot_id": snapshot.dataset_snapshot_id,
        "content_hash": snapshot.content_hash,
        "bar_count": len(manifest.bars),
        "asset_count": len(by_asset),
        "bars_by_asset": dict(sorted(by_asset.items())),
    }


def persist_research_bar_manifest(
    conn: Connection,
    store: VNextStore,
    manifest: ResearchBarManifest,
) -> dict[str, object]:
    """Persist one fully validated immutable dataset atomically."""
    report = validate_research_bar_manifest(manifest)
    actual_hash = research_dataset_content_hash(
        manifest.snapshot,
        manifest.bars,
    )
    if actual_hash != manifest.snapshot.content_hash:
        raise ValueError(
            "research dataset content_hash does not match normalized bar content"
        )

    snapshots = store.tables["research_dataset_snapshots"]
    existing = conn.execute(
        sa.select(snapshots.c.dataset_snapshot_id).where(
            snapshots.c.dataset_snapshot_id
            == manifest.snapshot.dataset_snapshot_id
        )
    ).first()
    if existing is not None:
        raise ValueError("research dataset snapshot already exists")

    store.record_research_dataset_snapshot(
        conn,
        manifest.snapshot,
    )
    table = store.tables["research_bars"]
    conn.execute(
        table.insert(),
        [
            {
                "research_bar_id": row.research_bar_id,
                "dataset_snapshot_id": row.dataset_snapshot_id,
                "asset_id": row.asset_id,
                "interval_seconds": row.interval_seconds,
                "bucket_open_utc": row.bucket_open_utc,
                "bucket_close_utc": row.bucket_close_utc,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "source_id": row.source_id,
                "source_data_version": row.source_data_version,
                "source_ref": row.source_ref,
                "available_at_utc": row.available_at_utc,
            }
            for row in sorted(
                manifest.bars,
                key=lambda item: (
                    item.asset_id,
                    item.interval_seconds,
                    item.bucket_open_utc,
                    item.research_bar_id,
                ),
            )
        ],
    )
    return {
        **report,
        "persisted": True,
    }
