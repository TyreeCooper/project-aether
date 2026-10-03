"""Persist Phase-13 intelligence source, health, conflict, and reaction history.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0027"
down_revision: Union[str, None] = "0026"
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
        "intelligence_sources",
        sa.Column("source_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("trust_state", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("ingestion_mode", sa.Text(), nullable=False),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.Column("operator_approved_by", sa.Text()),
        sa.Column("operator_approved_at_utc", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "trust_state IN ('candidate','trusted','untrusted','disabled')",
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
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intelligence_sources_asset_id",
        "intelligence_sources",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intelligence_sources_trust_state",
        "intelligence_sources",
        ["trust_state"],
        schema=SCHEMA,
    )

    op.create_table(
        "source_trust_decisions",
        sa.Column("decision_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.intelligence_sources.source_id"),
            nullable=False,
        ),
        sa.Column("prior_state", sa.Text(), nullable=False),
        sa.Column("new_state", sa.Text(), nullable=False),
        sa.Column("operator_id", sa.Text(), nullable=False),
        sa.Column("decided_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "prior_state IN ('candidate','trusted','untrusted','disabled')",
            name="ck_source_trust_prior_state",
        ),
        sa.CheckConstraint(
            "new_state IN ('candidate','trusted','untrusted','disabled')",
            name="ck_source_trust_new_state",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_source_trust_decisions_source_id",
        "source_trust_decisions",
        ["source_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_source_trust_decisions_decided_at_utc",
        "source_trust_decisions",
        ["decided_at_utc"],
        schema=SCHEMA,
    )

    op.create_table(
        "intelligence_health_snapshots",
        sa.Column("health_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at_utc", sa.DateTime(timezone=True)),
        sa.Column("age_seconds", sa.Float()),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "state IN ('healthy','partial','stale','degraded','unavailable','unconfigured')",
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
        schema=SCHEMA,
    )
    for column in ("source_id", "state", "observed_at_utc"):
        op.create_index(
            f"ix_intelligence_health_snapshots_{column}",
            "intelligence_health_snapshots",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "cross_source_conflict_assessments",
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("claim_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("value_fingerprints", sa.JSON(), nullable=False),
        sa.Column("assessed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "state IN ('insufficient','aligned','conflict')",
            name="ck_cross_source_conflict_state",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_cross_source_conflict_no_trade_influence",
        ),
        schema=SCHEMA,
    )
    for column in ("claim_key", "state", "assessed_at_utc"):
        op.create_index(
            f"ix_cross_source_conflict_assessments_{column}",
            "cross_source_conflict_assessments",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "event_reaction_measurements",
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("event_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "information_available_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("horizon_seconds", sa.Integer(), nullable=False),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
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
        schema=SCHEMA,
    )
    for column in ("event_id", "asset_id", "observed_at_utc"):
        op.create_index(
            f"ix_event_reaction_measurements_{column}",
            "event_reaction_measurements",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "event_reaction_rollups",
        sa.Column("rollup_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("event_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "information_available_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("market_data_version", sa.Text(), nullable=False),
        sa.Column("measurement_ids", sa.JSON(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("materialized_at_utc", sa.DateTime(timezone=True), nullable=False),
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
        schema=SCHEMA,
    )
    for column in ("event_id", "asset_id", "materialized_at_utc"):
        op.create_index(
            f"ix_event_reaction_rollups_{column}",
            "event_reaction_rollups",
            [column],
            schema=SCHEMA,
        )

    for table_name in (
        "source_trust_decisions",
        "intelligence_health_snapshots",
        "cross_source_conflict_assessments",
        "event_reaction_measurements",
        "event_reaction_rollups",
    ):
        _immutable_trigger(table_name)


def downgrade() -> None:
    for table_name in (
        "event_reaction_rollups",
        "event_reaction_measurements",
        "cross_source_conflict_assessments",
        "intelligence_health_snapshots",
        "source_trust_decisions",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON {SCHEMA}.{table_name}"
        )
    for table_name in (
        "event_reaction_rollups",
        "event_reaction_measurements",
        "cross_source_conflict_assessments",
        "intelligence_health_snapshots",
        "source_trust_decisions",
        "intelligence_sources",
    ):
        op.drop_table(table_name, schema=SCHEMA)
