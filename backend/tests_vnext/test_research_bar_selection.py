from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.research import ResearchDatasetSnapshot
from aether_vnext.research_bar_selection import (
    PITResearchBarSlice,
    select_pit_research_bars,
)
from aether_vnext.research_warehouse import (
    ResearchBarManifest,
    ResearchBarRecord,
    RESEARCH_BAR_MANIFEST_VERSION,
    research_bar_id,
    research_dataset_content_hash,
    _canonical_bar_payload,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _record(
    *,
    dataset_snapshot_id: str,
    asset_id: str,
    interval_seconds: int,
    opened: datetime,
    available: datetime,
    close: float,
) -> ResearchBarRecord:
    closed = opened + timedelta(seconds=interval_seconds)
    payload = _canonical_bar_payload(
        dataset_snapshot_id=dataset_snapshot_id,
        asset_id=asset_id,
        interval_seconds=interval_seconds,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open_=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        source_id="reviewed-history",
        source_data_version="v1",
        source_ref="reviewed-ref",
        available_at_utc=available,
    )
    return ResearchBarRecord(
        research_bar_id=research_bar_id(payload),
        dataset_snapshot_id=dataset_snapshot_id,
        asset_id=asset_id,
        interval_seconds=interval_seconds,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        source_id="reviewed-history",
        source_data_version="v1",
        source_ref="reviewed-ref",
        available_at_utc=available,
    )


def _manifest() -> ResearchBarManifest:
    dataset_id = "dataset-pit-1"
    bars = (
        _record(
            dataset_snapshot_id=dataset_id,
            asset_id="btc",
            interval_seconds=3600,
            opened=T0,
            available=T0 + timedelta(hours=1),
            close=100.0,
        ),
        _record(
            dataset_snapshot_id=dataset_id,
            asset_id="btc",
            interval_seconds=3600,
            opened=T0 + timedelta(hours=2),
            available=T0 + timedelta(hours=3),
            close=102.0,
        ),
        _record(
            dataset_snapshot_id=dataset_id,
            asset_id="btc",
            interval_seconds=3600,
            opened=T0 + timedelta(hours=3),
            available=T0 + timedelta(hours=5),
            close=103.0,
        ),
        _record(
            dataset_snapshot_id=dataset_id,
            asset_id="eth",
            interval_seconds=3600,
            opened=T0,
            available=T0 + timedelta(hours=1),
            close=200.0,
        ),
        _record(
            dataset_snapshot_id=dataset_id,
            asset_id="btc",
            interval_seconds=900,
            opened=T0,
            available=T0 + timedelta(minutes=15),
            close=99.0,
        ),
    )
    provisional = ResearchDatasetSnapshot(
        dataset_snapshot_id=dataset_id,
        created_at_utc=T0 + timedelta(days=1),
        as_of_utc=T0 + timedelta(hours=6),
        start_at_utc=T0,
        end_at_utc=T0 + timedelta(hours=6),
        asset_ids=("btc", "eth"),
        data_version="v1",
        source_registry_version="sources-v1",
        product_registry_version="products-v1",
        calendar_version="calendar-v1",
        pit=True,
        missing_data_policy="preserve_missing_intervals",
        content_hash="0" * 64,
    )
    content_hash = research_dataset_content_hash(provisional, bars)
    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=provisional.dataset_snapshot_id,
        created_at_utc=provisional.created_at_utc,
        as_of_utc=provisional.as_of_utc,
        start_at_utc=provisional.start_at_utc,
        end_at_utc=provisional.end_at_utc,
        asset_ids=provisional.asset_ids,
        data_version=provisional.data_version,
        source_registry_version=provisional.source_registry_version,
        product_registry_version=provisional.product_registry_version,
        calendar_version=provisional.calendar_version,
        pit=True,
        missing_data_policy=provisional.missing_data_policy,
        content_hash=content_hash,
    )
    return ResearchBarManifest(
        manifest_version=RESEARCH_BAR_MANIFEST_VERSION,
        source_ref="reviewed-manifest",
        snapshot=snapshot,
        bars=bars,
    )


def test_pit_slice_requires_nonempty_immutable_rows() -> None:
    with pytest.raises(ValueError, match="nonempty immutable tuple"):
        PITResearchBarSlice(
            dataset_snapshot_id="dataset-pit-1",
            asset_id="btc",
            interval_seconds=3600,
            as_of_utc=T0 + timedelta(hours=4),
            start_at_utc=None,
            rows=[],
        )


def test_pit_slice_rejects_row_identity_drift() -> None:
    manifest = _manifest()
    eth_row = next(row for row in manifest.bars if row.asset_id == "eth")

    with pytest.raises(
        ValueError,
        match="research bar asset does not match PIT selection",
    ):
        PITResearchBarSlice(
            dataset_snapshot_id=manifest.snapshot.dataset_snapshot_id,
            asset_id="btc",
            interval_seconds=3600,
            as_of_utc=T0 + timedelta(hours=4),
            start_at_utc=None,
            rows=(eth_row,),
        )


def test_selector_returns_only_available_matching_rows() -> None:
    manifest = _manifest()
    result = select_pit_research_bars(
        manifest,
        asset_id="btc",
        interval_seconds=3600,
        as_of_utc=T0 + timedelta(hours=4),
    )

    assert [row.close for row in result.rows] == [100.0, 102.0]
    assert result.first_bucket_open_utc == T0
    assert result.last_bucket_close_utc == T0 + timedelta(hours=3)


def test_selector_preserves_missing_intervals() -> None:
    result = select_pit_research_bars(
        _manifest(),
        asset_id="btc",
        interval_seconds=3600,
        as_of_utc=T0 + timedelta(hours=4),
    )

    assert result.rows[1].bucket_open_utc - result.rows[0].bucket_open_utc == (
        timedelta(hours=2)
    )
    assert len(result.rows) == 2


def test_unavailable_closed_bar_is_excluded_until_available() -> None:
    early = select_pit_research_bars(
        _manifest(),
        asset_id="btc",
        interval_seconds=3600,
        as_of_utc=T0 + timedelta(hours=4),
    )
    assert 103.0 not in [row.close for row in early.rows]

    later = select_pit_research_bars(
        _manifest(),
        asset_id="btc",
        interval_seconds=3600,
        as_of_utc=T0 + timedelta(hours=5),
    )
    assert [row.close for row in later.rows] == [100.0, 102.0, 103.0]


def test_selector_can_apply_explicit_start_boundary() -> None:
    result = select_pit_research_bars(
        _manifest(),
        asset_id="btc",
        interval_seconds=3600,
        as_of_utc=T0 + timedelta(hours=5),
        start_at_utc=T0 + timedelta(hours=2),
    )
    assert [row.close for row in result.rows] == [102.0, 103.0]


def test_selector_rejects_future_dataset_asof_and_empty_selection() -> None:
    manifest = _manifest()
    with pytest.raises(ValueError, match="cannot exceed"):
        select_pit_research_bars(
            manifest,
            asset_id="btc",
            interval_seconds=3600,
            as_of_utc=T0 + timedelta(hours=7),
        )

    with pytest.raises(ValueError, match="no PIT research bars"):
        select_pit_research_bars(
            manifest,
            asset_id="btc",
            interval_seconds=300,
            as_of_utc=T0 + timedelta(hours=4),
        )


@pytest.mark.parametrize("asset_id", (" BTC ", "BTC", 1))
def test_selector_requires_canonical_asset_identity(asset_id: object) -> None:
    with pytest.raises(
        ValueError,
        match="asset_id must be a canonical lowercase ID",
    ):
        select_pit_research_bars(
            _manifest(),
            asset_id=asset_id,
            interval_seconds=3600,
            as_of_utc=T0 + timedelta(hours=4),
        )


def test_selector_rejects_asset_outside_snapshot() -> None:
    with pytest.raises(ValueError, match="absent"):
        select_pit_research_bars(
            _manifest(),
            asset_id="nvda",
            interval_seconds=3600,
            as_of_utc=T0 + timedelta(hours=4),
        )
