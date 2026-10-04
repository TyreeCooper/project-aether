from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.research import ResearchDatasetSnapshot
from aether_vnext.research_warehouse import (
    RESEARCH_BAR_MANIFEST_VERSION,
    ResearchBarRecord,
    parse_research_bar_manifest,
    persist_research_bar_manifest,
    research_dataset_content_hash,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _payload() -> dict:
    base = {
        "manifest_version": RESEARCH_BAR_MANIFEST_VERSION,
        "source_ref": "reviewed-archive:example:v1",
        "snapshot": {
            "dataset_snapshot_id": "dataset:bars:v1",
            "created_at_utc": T0.isoformat(),
            "as_of_utc": T0.isoformat(),
            "start_at_utc": (T0 - timedelta(hours=3)).isoformat(),
            "end_at_utc": (T0 - timedelta(hours=1)).isoformat(),
            "asset_ids": ["btc", "eth"],
            "data_version": "reviewed-bars-v1",
            "source_registry_version": "reviewed-sources-v1",
            "product_registry_version": "products-v1",
            "calendar_version": "crypto-24x7-v1",
            "pit": True,
            "missing_data_policy": "no_synthetic_bars",
            "content_hash": "0" * 64,
        },
        "bars": [
            {
                "asset_id": "btc",
                "interval_seconds": 3600,
                "bucket_open_utc": (T0 - timedelta(hours=3)).isoformat(),
                "bucket_close_utc": (T0 - timedelta(hours=2)).isoformat(),
                "open": 100.0,
                "high": 104.0,
                "low": 99.0,
                "close": 103.0,
                "volume": 10.0,
                "source_id": "reviewed_source",
                "source_data_version": "source-v1",
                "available_at_utc": (T0 - timedelta(hours=2)).isoformat(),
            },
            {
                "asset_id": "eth",
                "interval_seconds": 3600,
                "bucket_open_utc": (T0 - timedelta(hours=2)).isoformat(),
                "bucket_close_utc": (T0 - timedelta(hours=1)).isoformat(),
                "open": 50.0,
                "high": 52.0,
                "low": 49.0,
                "close": 51.0,
                "volume": 20.0,
                "source_id": "reviewed_source",
                "source_data_version": "source-v1",
                "available_at_utc": (T0 - timedelta(hours=1)).isoformat(),
            },
        ],
    }

    snapshot_raw = base["snapshot"]
    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=snapshot_raw["dataset_snapshot_id"],
        created_at_utc=datetime.fromisoformat(snapshot_raw["created_at_utc"]),
        as_of_utc=datetime.fromisoformat(snapshot_raw["as_of_utc"]),
        start_at_utc=datetime.fromisoformat(snapshot_raw["start_at_utc"]),
        end_at_utc=datetime.fromisoformat(snapshot_raw["end_at_utc"]),
        asset_ids=tuple(snapshot_raw["asset_ids"]),
        data_version=snapshot_raw["data_version"],
        source_registry_version=snapshot_raw["source_registry_version"],
        product_registry_version=snapshot_raw["product_registry_version"],
        calendar_version=snapshot_raw["calendar_version"],
        pit=True,
        missing_data_policy=snapshot_raw["missing_data_policy"],
        content_hash="0" * 64,
    )
    rows = []
    for index, raw in enumerate(base["bars"]):
        opened = datetime.fromisoformat(raw["bucket_open_utc"])
        closed = datetime.fromisoformat(raw["bucket_close_utc"])
        available = datetime.fromisoformat(raw["available_at_utc"])
        rows.append(
            ResearchBarRecord(
                research_bar_id=f"fixture-{index}",
                dataset_snapshot_id=snapshot.dataset_snapshot_id,
                asset_id=raw["asset_id"],
                interval_seconds=raw["interval_seconds"],
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=raw["open"],
                high=raw["high"],
                low=raw["low"],
                close=raw["close"],
                volume=raw["volume"],
                source_id=raw["source_id"],
                source_data_version=raw["source_data_version"],
                source_ref=base["source_ref"],
                available_at_utc=available,
            )
        )

    # The dataset hash depends on canonical bar payload, including derived bar IDs.
    # Parse once with a placeholder hash is not allowed, so derive the canonical
    # IDs with the public parser's exact identity law by reproducing the manifest
    # through a temporary snapshot and stable payload shape.
    from aether_vnext.research_warehouse import (
        _canonical_bar_payload,
        research_bar_id,
    )
    canonical_rows = []
    for row in rows:
        payload = _canonical_bar_payload(
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
        canonical_rows.append(
            ResearchBarRecord(
                research_bar_id=research_bar_id(payload),
                dataset_snapshot_id=row.dataset_snapshot_id,
                asset_id=row.asset_id,
                interval_seconds=row.interval_seconds,
                bucket_open_utc=row.bucket_open_utc,
                bucket_close_utc=row.bucket_close_utc,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                source_id=row.source_id,
                source_data_version=row.source_data_version,
                source_ref=row.source_ref,
                available_at_utc=row.available_at_utc,
            )
        )
    base["snapshot"]["content_hash"] = research_dataset_content_hash(
        snapshot,
        tuple(canonical_rows),
    )
    return base


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_real_bar_manifest_is_content_addressed_and_persists_atomically() -> None:
    manifest = parse_research_bar_manifest(_payload())
    engine, store = _store()

    with engine.begin() as conn:
        report = persist_research_bar_manifest(conn, store, manifest)
        bars = tuple(
            conn.execute(
                sa.select(store.tables["research_bars"]).order_by(
                    store.tables["research_bars"].c.asset_id
                )
            ).mappings()
        )

    assert report["persisted"] is True
    assert report["bar_count"] == 2
    assert report["bars_by_asset"] == {"btc": 1, "eth": 1}
    assert len(bars) == 2
    assert all(row["dataset_snapshot_id"] == "dataset:bars:v1" for row in bars)


def test_content_hash_mismatch_is_rejected_before_persistence() -> None:
    payload = _payload()
    payload["bars"][0]["close"] = 102.5

    with pytest.raises(ValueError, match="content_hash"):
        parse_research_bar_manifest(payload)


def test_duplicate_asset_interval_bucket_is_rejected() -> None:
    payload = _payload()
    duplicate = deepcopy(payload["bars"][0])
    duplicate["high"] = 105.0
    payload["bars"].append(duplicate)

    # Recompute is unnecessary: duplicate identity must fail before accepting
    # a dataset regardless of the now-stale declared content hash.
    with pytest.raises(ValueError, match="duplicate research bar"):
        parse_research_bar_manifest(payload)


@pytest.mark.parametrize("interval", (3600.5, "3600", True))
def test_bar_interval_requires_exact_positive_integer(interval: object) -> None:
    payload = _payload()
    payload["bars"][0]["interval_seconds"] = interval

    with pytest.raises(
        ValueError,
        match="interval_seconds must be a positive integer",
    ):
        parse_research_bar_manifest(payload)


@pytest.mark.parametrize("field", ("open", "high", "low", "close", "volume"))
def test_bar_ohlcv_rejects_boolean_values(field: str) -> None:
    payload = _payload()
    payload["bars"][0][field] = True

    with pytest.raises(
        ValueError,
        match="prices/volume must be numeric, not boolean",
    ):
        parse_research_bar_manifest(payload)


def test_bar_bucket_duration_must_match_declared_interval() -> None:
    payload = _payload()
    payload["bars"][0]["interval_seconds"] = 1800

    with pytest.raises(
        ValueError,
        match="bucket duration must equal interval_seconds",
    ):
        parse_research_bar_manifest(payload)


def test_bar_cannot_be_available_before_close() -> None:
    payload = _payload()
    payload["bars"][0]["available_at_utc"] = (
        T0 - timedelta(hours=2, seconds=1)
    ).isoformat()

    with pytest.raises(ValueError, match="before bucket close"):
        parse_research_bar_manifest(payload)


def test_declared_dataset_asset_requires_at_least_one_real_bar() -> None:
    payload = _payload()
    payload["bars"] = [
        row for row in payload["bars"] if row["asset_id"] != "eth"
    ]

    with pytest.raises(ValueError, match="assets with no bars"):
        parse_research_bar_manifest(payload)


def test_missing_time_buckets_are_not_synthesized() -> None:
    payload = _payload()
    payload["snapshot"]["asset_ids"] = ["btc"]
    payload["bars"] = [payload["bars"][0]]
    # Shift the single BTC bar earlier; no importer rule creates an intermediate bar.
    payload["bars"][0]["bucket_open_utc"] = (
        T0 - timedelta(hours=3)
    ).isoformat()
    payload["bars"][0]["bucket_close_utc"] = (
        T0 - timedelta(hours=2)
    ).isoformat()
    payload["bars"][0]["available_at_utc"] = (
        T0 - timedelta(hours=2)
    ).isoformat()

    # Build a valid one-bar content hash using the same helper path as _payload.
    source = payload["bars"][0]
    snapshot_raw = payload["snapshot"]
    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=snapshot_raw["dataset_snapshot_id"],
        created_at_utc=datetime.fromisoformat(snapshot_raw["created_at_utc"]),
        as_of_utc=datetime.fromisoformat(snapshot_raw["as_of_utc"]),
        start_at_utc=datetime.fromisoformat(snapshot_raw["start_at_utc"]),
        end_at_utc=datetime.fromisoformat(snapshot_raw["end_at_utc"]),
        asset_ids=("btc",),
        data_version=snapshot_raw["data_version"],
        source_registry_version=snapshot_raw["source_registry_version"],
        product_registry_version=snapshot_raw["product_registry_version"],
        calendar_version=snapshot_raw["calendar_version"],
        pit=True,
        missing_data_policy=snapshot_raw["missing_data_policy"],
        content_hash="0" * 64,
    )
    from aether_vnext.research_warehouse import (
        _canonical_bar_payload,
        research_bar_id,
    )
    canonical = _canonical_bar_payload(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=datetime.fromisoformat(source["bucket_open_utc"]),
        bucket_close_utc=datetime.fromisoformat(source["bucket_close_utc"]),
        open_=source["open"],
        high=source["high"],
        low=source["low"],
        close=source["close"],
        volume=source["volume"],
        source_id=source["source_id"],
        source_data_version=source["source_data_version"],
        source_ref=payload["source_ref"],
        available_at_utc=datetime.fromisoformat(source["available_at_utc"]),
    )
    record = ResearchBarRecord(
        research_bar_id=research_bar_id(canonical),
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=datetime.fromisoformat(source["bucket_open_utc"]),
        bucket_close_utc=datetime.fromisoformat(source["bucket_close_utc"]),
        open=source["open"],
        high=source["high"],
        low=source["low"],
        close=source["close"],
        volume=source["volume"],
        source_id=source["source_id"],
        source_data_version=source["source_data_version"],
        source_ref=payload["source_ref"],
        available_at_utc=datetime.fromisoformat(source["available_at_utc"]),
    )
    payload["snapshot"]["content_hash"] = research_dataset_content_hash(
        snapshot,
        (record,),
    )

    manifest = parse_research_bar_manifest(payload)
    assert len(manifest.bars) == 1
