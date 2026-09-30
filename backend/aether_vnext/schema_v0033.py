"""FROZEN revision-0033 SQLAlchemy metadata for AETHER vNext.

Revision 0033 adds an isolated prototype market-bar ledger. These rows are runtime
warm-up/decision inputs only; they are not held-out research evidence and cannot be
used to satisfy Phase 18 evidence gates.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0032 import build_metadata as build_metadata_v0032


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0032(schema=schema)

    sa.Table(
        "prototype_market_bars",
        md,
        sa.Column("bar_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("bucket_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("available_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_id",
            "interval_seconds",
            "bucket_open_utc",
            "source_id",
            name="uq_prototype_market_bar_identity",
        ),
        sa.CheckConstraint("interval_seconds > 0", name="ck_prototype_bar_interval_positive"),
        sa.CheckConstraint("bucket_close_utc > bucket_open_utc", name="ck_prototype_bar_time_order"),
        sa.CheckConstraint("available_at_utc >= bucket_close_utc", name="ck_prototype_bar_available_after_close"),
        sa.CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_prototype_bar_prices_positive"),
        sa.CheckConstraint("high >= low", name="ck_prototype_bar_high_low"),
        sa.CheckConstraint("volume >= 0", name="ck_prototype_bar_volume_nonnegative"),
        sa.CheckConstraint("trade_count >= 0", name="ck_prototype_bar_trade_count_nonnegative"),
    )
    sa.Index(
        "ix_prototype_market_bars_asset_interval_close",
        md.tables[
            f"{schema}.prototype_market_bars"
            if schema
            else "prototype_market_bars"
        ].c.asset_id,
        md.tables[
            f"{schema}.prototype_market_bars"
            if schema
            else "prototype_market_bars"
        ].c.interval_seconds,
        md.tables[
            f"{schema}.prototype_market_bars"
            if schema
            else "prototype_market_bars"
        ].c.bucket_close_utc,
    )
    return md


METADATA = build_metadata()
