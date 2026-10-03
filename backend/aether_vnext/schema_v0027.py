"""FROZEN revision-0027 SQLAlchemy metadata for AETHER vNext.

Revision 0027 adds durable Phase-13 News-Market Intelligence persistence while
preserving every table from revision 0026.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0026 import build_metadata as build_metadata_v0026


TRUST_STATES_SQL = "'candidate','trusted','untrusted','disabled'"
HEALTH_STATES_SQL = (
    "'healthy','partial','stale','degraded','unavailable','unconfigured'"
)
CONFLICT_STATES_SQL = "'insufficient','aligned','conflict'"


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0026(schema=schema)

    sa.Table(
        "intelligence_sources",
        md,
        sa.Column("source_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("trust_state", sa.Text(), nullable=False, index=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("ingestion_mode", sa.Text(), nullable=False),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.Column("operator_approved_by", sa.Text()),
        sa.Column("operator_approved_at_utc", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"trust_state IN ({TRUST_STATES_SQL})",
            name="ck_intelligence_source_trust_state",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_intelligence_source_no_trade_influence",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_intelligence_source_row_version",
        ),
    )

    sa.Table(
        "source_trust_decisions",
        md,
        sa.Column("decision_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "intelligence_sources.source_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("prior_state", sa.Text(), nullable=False),
        sa.Column("new_state", sa.Text(), nullable=False),
        sa.Column("operator_id", sa.Text(), nullable=False),
        sa.Column(
            "decided_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"prior_state IN ({TRUST_STATES_SQL})",
            name="ck_source_trust_prior_state",
        ),
        sa.CheckConstraint(
            f"new_state IN ({TRUST_STATES_SQL})",
            name="ck_source_trust_new_state",
        ),
    )

    sa.Table(
        "intelligence_health_snapshots",
        md,
        sa.Column("health_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False, index=True),
        sa.Column("state", sa.Text(), nullable=False, index=True),
        sa.Column(
            "observed_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("last_success_at_utc", sa.DateTime(timezone=True)),
        sa.Column("age_seconds", sa.Float()),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"state IN ({HEALTH_STATES_SQL})",
            name="ck_intelligence_health_state",
        ),
        sa.CheckConstraint(
            "age_seconds IS NULL OR age_seconds >= 0",
            name="ck_intelligence_health_age",
        ),
        sa.CheckConstraint(
            "stale_after_seconds > 0",
            name="ck_intelligence_health_stale_after",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_intelligence_health_no_trade_influence",
        ),
    )

    sa.Table(
        "cross_source_conflict_assessments",
        md,
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("claim_key", sa.Text(), nullable=False, index=True),
        sa.Column("state", sa.Text(), nullable=False, index=True),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("value_fingerprints", sa.JSON(), nullable=False),
        sa.Column(
            "assessed_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"state IN ({CONFLICT_STATES_SQL})",
            name="ck_cross_source_conflict_state",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_cross_source_conflict_no_trade_influence",
        ),
    )

    sa.Table(
        "event_reaction_measurements",
        md,
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False, index=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("event_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "information_available_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("horizon_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "observed_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("return_value", sa.Float(), nullable=False),
        sa.Column("market_data_version", sa.Text(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "asset_id",
            "market_data_version",
            "horizon_seconds",
            name="uq_event_reaction_event_asset_market_horizon",
        ),
        sa.CheckConstraint(
            "horizon_seconds IN (300,900,1800,3600,14400,86400)",
            name="ck_event_reaction_horizon",
        ),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_event_reaction_research_only",
        ),
    )

    sa.Table(
        "event_reaction_rollups",
        md,
        sa.Column("rollup_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False, index=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("event_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "information_available_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("market_data_version", sa.Text(), nullable=False),
        sa.Column("measurement_ids", sa.JSON(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column(
            "materialized_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "asset_id",
            "market_data_version",
            "materialized_at_utc",
            name="uq_event_reaction_rollup_materialization",
        ),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_event_reaction_rollup_research_only",
        ),
    )
    return md


def _fk(schema: str | None, target: str) -> str:
    return f"{schema}.{target}" if schema else target


METADATA = build_metadata()
