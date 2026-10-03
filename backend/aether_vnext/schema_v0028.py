"""FROZEN revision-0028 SQLAlchemy metadata for AETHER vNext.

Revision 0028 adds the durable F-007 news/event intelligence ledger while
preserving every table from revision 0027.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0027 import build_metadata as build_metadata_v0027


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0027(schema=schema)

    sa.Table(
        "news_sources",
        md,
        sa.Column("source_id", sa.Text(), primary_key=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_class", sa.Text(), nullable=False),
        sa.Column("primary_or_secondary", sa.Text(), nullable=False),
        sa.Column("authority_class", sa.Text(), nullable=False),
        sa.Column("base_timezone", sa.Text(), nullable=False),
        sa.Column("provider_adapter_id", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("terms_licensing_metadata_ref", sa.Text()),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("row_version >= 1", name="ck_news_source_row_version"),
    )

    sa.Table(
        "raw_news_items",
        md,
        sa.Column("news_item_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "news_sources.source_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("provider_item_id", sa.Text()),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("published_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("first_seen_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_of_news_item_id", sa.Text()),
        sa.Column("correction_or_retraction", sa.Boolean(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("ingest_status", sa.Text(), nullable=False, index=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False, index=True),
        sa.Column("raw_payload_ref", sa.Text(), nullable=False),
    )

    sa.Table(
        "normalized_events",
        md,
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_cluster_id", sa.Text(), nullable=False, index=True),
        sa.Column("event_type", sa.Text(), nullable=False, index=True),
        sa.Column("source_news_item_ids", sa.JSON(), nullable=False),
        sa.Column("assets", sa.JSON(), nullable=False),
        sa.Column("clusters", sa.JSON(), nullable=False),
        sa.Column("canonical_event_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("information_available_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("scheduled", sa.Boolean(), nullable=False),
        sa.Column("expected", sa.Boolean()),
        sa.Column("consensus", sa.JSON()),
        sa.Column("actual", sa.JSON()),
        sa.Column("surprise_magnitude", sa.Float()),
        sa.Column("direction", sa.Text()),
        sa.Column("severity", sa.Float()),
        sa.Column("novelty", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("market_scope", sa.Text(), nullable=False),
        sa.Column("company_specific", sa.Boolean(), nullable=False),
        sa.Column("sector_specific", sa.Boolean(), nullable=False),
        sa.Column("macro", sa.Boolean(), nullable=False),
        sa.Column("geopolitical", sa.Boolean(), nullable=False),
        sa.Column("regulatory", sa.Boolean(), nullable=False),
        sa.Column("earnings", sa.Boolean(), nullable=False),
        sa.Column("policy", sa.Boolean(), nullable=False),
        sa.Column("supply", sa.Boolean(), nullable=False),
        sa.Column("demand", sa.Boolean(), nullable=False),
        sa.Column("liquidity", sa.Boolean(), nullable=False),
        sa.Column("normalizer_version", sa.Text(), nullable=False),
    )

    sa.Table(
        "event_asset_links",
        md,
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_source_ids", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("linker_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "event_id",
            "asset_id",
            "relation_type",
            "linker_version",
            name="pk_event_asset_links",
        ),
    )

    sa.Table(
        "event_market_responses",
        md,
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("pre_event_observation_id", sa.Text(), nullable=False),
        sa.Column("return_1m", sa.Float()),
        sa.Column("return_5m", sa.Float()),
        sa.Column("return_15m", sa.Float()),
        sa.Column("return_1h", sa.Float()),
        sa.Column("return_4h", sa.Float()),
        sa.Column("return_1d", sa.Float()),
        sa.Column("mfe", sa.Float()),
        sa.Column("mae", sa.Float()),
        sa.Column("realized_vol_change", sa.Float()),
        sa.Column("volume_change", sa.Float()),
        sa.Column("spread_change", sa.Float()),
        sa.Column("liquidity_change", sa.Float()),
        sa.Column("correlation_change", sa.Float()),
        sa.Column("continuation_or_reversal", sa.Text()),
        sa.Column("stabilization_time", sa.Float()),
        sa.Column("market_data_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "event_id",
            "asset_id",
            "market_data_version",
            name="pk_event_market_responses",
        ),
    )

    sa.Table(
        "historical_analog_runs",
        md,
        sa.Column("analog_run_id", sa.Text(), primary_key=True),
        sa.Column("query_event_or_state_id", sa.Text(), nullable=False, index=True),
        sa.Column("feature_spec_version", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("eligible_history_cutoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_event_ids", sa.JSON(), nullable=False),
        sa.Column("similarity_scores", sa.JSON(), nullable=False),
        sa.Column("outcome_distribution", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.CheckConstraint("research_only = true", name="ck_historical_analog_research_only"),
    )
    return md


def _fk(schema: str | None, target: str) -> str:
    return f"{schema}.{target}" if schema else target


METADATA = build_metadata()
