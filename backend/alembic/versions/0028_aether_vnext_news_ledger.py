"""Persist the F-007 news/event intelligence ledger.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def _immutable_trigger(table_name: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table_name}_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def upgrade() -> None:
    op.create_table(
        "news_sources",
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
        schema=SCHEMA,
    )

    op.create_table(
        "raw_news_items",
        sa.Column("news_item_id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.news_sources.source_id"), nullable=False),
        sa.Column("provider_item_id", sa.Text()),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("published_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_of_news_item_id", sa.Text()),
        sa.Column("correction_or_retraction", sa.Boolean(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("ingest_status", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("raw_payload_ref", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    for column in ("source_id", "published_at_utc", "first_seen_at_utc", "ingest_status", "dedupe_key"):
        op.create_index(f"ix_raw_news_items_{column}", "raw_news_items", [column], schema=SCHEMA)

    op.create_table(
        "normalized_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_cluster_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_news_item_ids", sa.JSON(), nullable=False),
        sa.Column("assets", sa.JSON(), nullable=False),
        sa.Column("clusters", sa.JSON(), nullable=False),
        sa.Column("canonical_event_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("information_available_at_utc", sa.DateTime(timezone=True), nullable=False),
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
        schema=SCHEMA,
    )
    for column in ("event_cluster_id", "event_type", "canonical_event_at_utc", "information_available_at_utc"):
        op.create_index(f"ix_normalized_events_{column}", "normalized_events", [column], schema=SCHEMA)

    op.create_table(
        "event_asset_links",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_source_ids", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linker_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "asset_id", "relation_type", "linker_version", name="pk_event_asset_links"),
        schema=SCHEMA,
    )
    op.create_index("ix_event_asset_links_created_at_utc", "event_asset_links", ["created_at_utc"], schema=SCHEMA)

    op.create_table(
        "event_market_responses",
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
        sa.PrimaryKeyConstraint("event_id", "asset_id", "market_data_version", name="pk_event_market_responses"),
        schema=SCHEMA,
    )

    op.create_table(
        "historical_analog_runs",
        sa.Column("analog_run_id", sa.Text(), primary_key=True),
        sa.Column("query_event_or_state_id", sa.Text(), nullable=False),
        sa.Column("feature_spec_version", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible_history_cutoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_event_ids", sa.JSON(), nullable=False),
        sa.Column("similarity_scores", sa.JSON(), nullable=False),
        sa.Column("outcome_distribution", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.CheckConstraint("research_only = true", name="ck_historical_analog_research_only"),
        schema=SCHEMA,
    )
    for column in ("query_event_or_state_id", "as_of_utc", "created_at_utc"):
        op.create_index(f"ix_historical_analog_runs_{column}", "historical_analog_runs", [column], schema=SCHEMA)

    for table_name in (
        "raw_news_items",
        "normalized_events",
        "event_asset_links",
        "event_market_responses",
        "historical_analog_runs",
    ):
        _immutable_trigger(table_name)


def downgrade() -> None:
    for table_name in (
        "historical_analog_runs",
        "event_market_responses",
        "event_asset_links",
        "normalized_events",
        "raw_news_items",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {SCHEMA}.{table_name}")
    for table_name in (
        "historical_analog_runs",
        "event_market_responses",
        "event_asset_links",
        "normalized_events",
        "raw_news_items",
        "news_sources",
    ):
        op.drop_table(table_name, schema=SCHEMA)
