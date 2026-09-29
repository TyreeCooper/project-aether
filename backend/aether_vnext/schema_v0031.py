"""FROZEN revision-0031 SQLAlchemy metadata for AETHER vNext.

Revision 0031 adds the durable Phase-14 historical crisis/regime archive while
preserving every table from revision 0030.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0030 import build_metadata as build_metadata_v0030


CRISIS_REGIME_CATEGORY_SQL = (
    "category IN ("
    "'crash_flash_crash',"
    "'volatility_expansion_compression',"
    "'liquidity_crisis',"
    "'rate_inflation_shock',"
    "'geopolitical_shock',"
    "'bank_exchange_failure',"
    "'commodity_shock',"
    "'earnings_guidance_gap',"
    "'regulatory_shock',"
    "'crypto_failure_venue_incident',"
    "'policy_reversal',"
    "'scheduled_macro_surprise'"
    ")"
)


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0030(schema=schema)

    sa.Table(
        "crisis_regime_archive_entries",
        md,
        sa.Column("archive_id", sa.Text(), primary_key=True),
        sa.Column("category", sa.Text(), nullable=False, index=True),
        sa.Column("episode_ref", sa.Text(), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("regime_ids", sa.JSON(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("ended_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("source_record_ids", sa.JSON(), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            CRISIS_REGIME_CATEGORY_SQL,
            name="ck_crisis_regime_archive_category",
        ),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_crisis_regime_archive_research_only",
        ),
        sa.CheckConstraint(
            "ended_at_utc >= started_at_utc",
            name="ck_crisis_regime_archive_time_order",
        ),
        sa.CheckConstraint(
            "recorded_at_utc >= started_at_utc",
            name="ck_crisis_regime_archive_recorded_order",
        ),
    )
    return md


METADATA = build_metadata()
