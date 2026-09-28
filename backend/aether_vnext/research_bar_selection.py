"""Point-in-time selection of immutable AETHER research bars.

This module selects already-validated ResearchBarRecord rows for historical replay.
It does not synthesize bars, fill missing buckets, infer exchange-print timestamps,
or mutate the research warehouse.

A row is visible only when both:
- its completed bucket is at or before the requested as-of timestamp; and
- its reviewed available_at_utc is at or before that as-of timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.research_warehouse import (
    ResearchBarManifest,
    ResearchBarRecord,
    validate_research_bar_manifest,
)


@dataclass(frozen=True, slots=True)
class PITResearchBarSlice:
    dataset_snapshot_id: str
    asset_id: str
    interval_seconds: int
    as_of_utc: datetime
    start_at_utc: datetime | None
    rows: tuple[ResearchBarRecord, ...]

    @property
    def first_bucket_open_utc(self) -> datetime:
        return self.rows[0].bucket_open_utc

    @property
    def last_bucket_close_utc(self) -> datetime:
        return self.rows[-1].bucket_close_utc


def select_pit_research_bars(
    manifest: ResearchBarManifest,
    *,
    asset_id: str,
    interval_seconds: int,
    as_of_utc: datetime,
    start_at_utc: datetime | None = None,
) -> PITResearchBarSlice:
    """Return one ordered, no-lookahead immutable research-bar slice."""
    validate_research_bar_manifest(manifest)

    if (
        not isinstance(asset_id, str)
        or not asset_id
        or asset_id != asset_id.strip()
        or asset_id != asset_id.lower()
    ):
        raise ValueError("asset_id must be a canonical lowercase ID")
    asset = asset_id
    if asset not in manifest.snapshot.asset_ids:
        raise ValueError("asset_id is absent from research dataset snapshot")
    if (
        not isinstance(interval_seconds, int)
        or isinstance(interval_seconds, bool)
        or interval_seconds <= 0
    ):
        raise ValueError("interval_seconds must be a positive integer")
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if as_of_utc > manifest.snapshot.as_of_utc:
        raise ValueError(
            "as_of_utc cannot exceed research dataset snapshot as_of_utc"
        )
    if start_at_utc is not None:
        if start_at_utc.tzinfo is None:
            raise ValueError("start_at_utc must be timezone-aware")
        if start_at_utc > as_of_utc:
            raise ValueError("start_at_utc cannot exceed as_of_utc")

    rows = tuple(
        sorted(
            (
                row
                for row in manifest.bars
                if row.asset_id == asset
                and row.interval_seconds == interval_seconds
                and row.bucket_close_utc <= as_of_utc
                and row.available_at_utc <= as_of_utc
                and (
                    start_at_utc is None
                    or row.bucket_open_utc >= start_at_utc
                )
            ),
            key=lambda row: (
                row.bucket_open_utc,
                row.bucket_close_utc,
                row.research_bar_id,
            ),
        )
    )
    if not rows:
        raise ValueError(
            "no PIT research bars match asset/interval/as-of selection"
        )

    prior_open: datetime | None = None
    prior_close: datetime | None = None
    for row in rows:
        if prior_open is not None and row.bucket_open_utc <= prior_open:
            raise ValueError("selected research bars are not strictly ordered")
        if prior_close is not None and row.bucket_close_utc <= prior_close:
            raise ValueError(
                "selected research bar closes are not strictly ordered"
            )
        prior_open = row.bucket_open_utc
        prior_close = row.bucket_close_utc

    return PITResearchBarSlice(
        dataset_snapshot_id=manifest.snapshot.dataset_snapshot_id,
        asset_id=asset,
        interval_seconds=interval_seconds,
        as_of_utc=as_of_utc,
        start_at_utc=start_at_utc,
        rows=rows,
    )
