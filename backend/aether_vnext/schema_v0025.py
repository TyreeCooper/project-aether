"""FROZEN revision-0025 SQLAlchemy metadata for AETHER vNext.

Revision 0025 adds the immutable point-in-time research-bar warehouse while
preserving every table from revision 0024.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0024 import build_metadata as build_metadata_v0024


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0024(schema=schema)

    sa.Table(
        "research_bars",
        md,
        sa.Column("research_bar_id", sa.Text(), primary_key=True),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(
                _fk(schema, "research_dataset_snapshots.dataset_snapshot_id")
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("bucket_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_data_version", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("available_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "dataset_snapshot_id",
            "asset_id",
            "interval_seconds",
            "bucket_open_utc",
            name="uq_research_bar_dataset_asset_interval_open",
        ),
        sa.CheckConstraint(
            "interval_seconds > 0",
            name="ck_research_bar_interval_positive",
        ),
        sa.CheckConstraint(
            "bucket_open_utc < bucket_close_utc",
            name="ck_research_bar_window_order",
        ),
        sa.CheckConstraint(
            "available_at_utc >= bucket_close_utc",
            name="ck_research_bar_available_after_close",
        ),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="ck_research_bar_prices_positive",
        ),
        sa.CheckConstraint(
            "high >= open AND high >= close AND high >= low",
            name="ck_research_bar_high_consistent",
        ),
        sa.CheckConstraint(
            "low <= open AND low <= close AND low <= high",
            name="ck_research_bar_low_consistent",
        ),
        sa.CheckConstraint(
            "volume >= 0",
            name="ck_research_bar_volume_nonnegative",
        ),
    )
    return md


def _fk(schema: str | None, target: str) -> str:
    return f"{schema}.{target}" if schema else target


METADATA = build_metadata()
