from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.research_bar_manifest_assembly import (
    ResearchDatasetSpec,
    assemble_research_bar_manifest,
)
from aether_vnext.research_warehouse import (
    RESEARCH_BAR_MANIFEST_VERSION,
    research_dataset_content_hash,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _spec(
    *,
    asset_ids: tuple[str, ...] = ("btc", "eth"),
) -> ResearchDatasetSpec:
    return ResearchDatasetSpec(
        dataset_snapshot_id="dataset-reviewed-v1",
        created_at_utc=T0 + timedelta(days=10),
        as_of_utc=T0 + timedelta(days=10),
        start_at_utc=T0,
        end_at_utc=T0 + timedelta(days=9),
        asset_ids=asset_ids,
        data_version="reviewed-bars-v1",
        source_registry_version="sources-v1",
        product_registry_version="products-v1",
        calendar_version="calendars-v1",
        missing_data_policy="fail_closed",
    )


def _row(
    *,
    asset_id: str,
    opened: datetime,
    source_ref: str | None = None,
) -> dict[str, object]:
    closed = opened + timedelta(hours=1)
    row: dict[str, object] = {
        "asset_id": asset_id,
        "interval_seconds": 3600,
        "bucket_open_utc": opened,
        "bucket_close_utc": closed,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "source_id": "reviewed-provider",
        "source_data_version": "history-v1",
        "available_at_utc": closed,
    }
    if source_ref is not None:
        row["source_ref"] = source_ref
    return row


def test_assembler_computes_content_hash_and_validates_manifest() -> None:
    rows = (
        _row(asset_id="eth", opened=T0 + timedelta(hours=1)),
        _row(
            asset_id="btc",
            opened=T0,
            source_ref="btc-reviewed-source",
        ),
    )
    out = assemble_research_bar_manifest(
        source_ref="dataset-reviewed-source",
        dataset_spec=_spec(),
        bar_rows=rows,
    )

    manifest = out.manifest
    assert manifest.manifest_version == RESEARCH_BAR_MANIFEST_VERSION
    assert len(manifest.snapshot.content_hash) == 64
    assert manifest.snapshot.content_hash != "0" * 64
    assert manifest.snapshot.content_hash == research_dataset_content_hash(
        manifest.snapshot,
        manifest.bars,
    )
    assert out.validation_report["bar_count"] == 2
    assert out.validation_report["asset_count"] == 2
    assert tuple(row.asset_id for row in manifest.bars) == ("btc", "eth")
    assert manifest.bars[0].source_ref == "btc-reviewed-source"
    assert manifest.bars[1].source_ref == "dataset-reviewed-source"


def test_assembler_is_deterministic_across_input_order() -> None:
    btc = _row(asset_id="btc", opened=T0)
    eth = _row(asset_id="eth", opened=T0 + timedelta(hours=1))

    first = assemble_research_bar_manifest(
        source_ref="dataset-source",
        dataset_spec=_spec(),
        bar_rows=(btc, eth),
    )
    second = assemble_research_bar_manifest(
        source_ref="dataset-source",
        dataset_spec=_spec(),
        bar_rows=(eth, btc),
    )

    assert (
        first.manifest.snapshot.content_hash
        == second.manifest.snapshot.content_hash
    )
    assert (
        tuple(row.research_bar_id for row in first.manifest.bars)
        == tuple(row.research_bar_id for row in second.manifest.bars)
    )


def test_declared_asset_without_bars_fails_closed() -> None:
    with pytest.raises(ValueError, match="assets with no bars"):
        assemble_research_bar_manifest(
            source_ref="dataset-source",
            dataset_spec=_spec(asset_ids=("btc", "eth")),
            bar_rows=(_row(asset_id="btc", opened=T0),),
        )


def test_duplicate_asset_interval_bucket_fails_closed() -> None:
    row = _row(asset_id="btc", opened=T0)
    with pytest.raises(ValueError, match="duplicate research bar"):
        assemble_research_bar_manifest(
            source_ref="dataset-source",
            dataset_spec=_spec(asset_ids=("btc",)),
            bar_rows=(row, dict(row)),
        )


def test_assembler_requires_explicit_completed_bar_times() -> None:
    row = _row(asset_id="btc", opened=T0)
    row["bucket_close_utc"] = row["bucket_open_utc"]

    with pytest.raises(ValueError, match="close after bucket open"):
        assemble_research_bar_manifest(
            source_ref="dataset-source",
            dataset_spec=_spec(asset_ids=("btc",)),
            bar_rows=(row,),
        )


def test_assembler_rejects_mutable_or_empty_bar_collection() -> None:
    with pytest.raises(ValueError, match="immutable tuple"):
        assemble_research_bar_manifest(
            source_ref="dataset-source",
            dataset_spec=_spec(asset_ids=("btc",)),
            bar_rows=[],
        )
