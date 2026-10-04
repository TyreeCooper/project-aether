"""Persist Phase-14 Institutional Memory and P&L Attribution.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0030"
down_revision: Union[str, None] = "0029"
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
        "pnl_attributions",
        sa.Column("attribution_id", sa.Text(), primary_key=True),
        sa.Column("firm_id", sa.Text(), nullable=False),
        sa.Column("mechanism_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("regime_id", sa.Text(), nullable=False),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("net_pnl_usd", sa.Float(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("attributed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_ids", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    for column in (
        "firm_id",
        "mechanism_id",
        "playbook_id",
        "route_id",
        "asset_id",
        "regime_id",
        "trade_id",
        "attributed_at_utc",
    ):
        op.create_index(
            f"ix_pnl_attributions_{column}",
            "pnl_attributions",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "institutional_memories",
        sa.Column("memory_id", sa.Text(), primary_key=True),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("market_state_ref", sa.Text(), nullable=False),
        sa.Column("information_state_ref", sa.Text(), nullable=False),
        sa.Column("signal_ref", sa.Text(), nullable=False),
        sa.Column("decision_ref", sa.Text(), nullable=False),
        sa.Column("expected_outcome_ref", sa.Text(), nullable=False),
        sa.Column("actual_outcome_ref", sa.Text(), nullable=False),
        sa.Column("execution_quality_ref", sa.Text(), nullable=False),
        sa.Column("risk_state_ref", sa.Text(), nullable=False),
        sa.Column("success_failure_reason", sa.Text(), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("future_relevance", sa.JSON(), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_ids", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    for column in ("trade_id", "route_id", "occurred_at_utc", "recorded_at_utc"):
        op.create_index(
            f"ix_institutional_memories_{column}",
            "institutional_memories",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "failure_archive_entries",
        sa.Column("failure_id", sa.Text(), primary_key=True),
        sa.Column("memory_id", sa.Text(), nullable=False),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recovery_lesson", sa.Text(), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_ids", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    for column in ("memory_id", "trade_id", "category", "recorded_at_utc"):
        op.create_index(
            f"ix_failure_archive_entries_{column}",
            "failure_archive_entries",
            [column],
            schema=SCHEMA,
        )

    op.create_table(
        "counterfactual_replays",
        sa.Column("replay_id", sa.Text(), primary_key=True),
        sa.Column("original_memory_id", sa.Text(), nullable=False),
        sa.Column("variation_keys", sa.JSON(), nullable=False),
        sa.Column("hypothetical_result_ref", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hypothetical", sa.Boolean(), nullable=False),
        sa.Column("independent_evidence_credit", sa.Boolean(), nullable=False),
        sa.CheckConstraint("hypothetical = true", name="ck_counterfactual_replay_hypothetical"),
        sa.CheckConstraint(
            "independent_evidence_credit = false",
            name="ck_counterfactual_no_independent_evidence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_counterfactual_replays_original_memory_id",
        "counterfactual_replays",
        ["original_memory_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_counterfactual_replays_created_at_utc",
        "counterfactual_replays",
        ["created_at_utc"],
        schema=SCHEMA,
    )

    op.create_table(
        "experience_coverage_snapshots",
        sa.Column("coverage_id", sa.Text(), primary_key=True),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("historical_years", sa.Float(), nullable=False),
        sa.Column("unique_regimes_crises", sa.Integer(), nullable=False),
        sa.Column("event_categories", sa.Integer(), nullable=False),
        sa.Column("asset_event_combinations", sa.Integer(), nullable=False),
        sa.Column("execution_failure_scenarios", sa.Integer(), nullable=False),
        sa.Column("correlation_stress_scenarios", sa.Integer(), nullable=False),
        sa.Column("unique_market_state_clusters", sa.Integer(), nullable=False),
        sa.Column("forward_paper_days", sa.Integer(), nullable=False),
        sa.Column("forward_paper_trades", sa.Integer(), nullable=False),
        sa.Column("historical_forward_gaps", sa.Integer(), nullable=False),
        sa.CheckConstraint("historical_years >= 0", name="ck_experience_coverage_years"),
        sa.CheckConstraint(
            "unique_regimes_crises >= 0 AND event_categories >= 0 "
            "AND asset_event_combinations >= 0 AND execution_failure_scenarios >= 0 "
            "AND correlation_stress_scenarios >= 0 AND unique_market_state_clusters >= 0 "
            "AND forward_paper_days >= 0 AND forward_paper_trades >= 0 "
            "AND historical_forward_gaps >= 0",
            name="ck_experience_coverage_nonnegative",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_experience_coverage_snapshots_as_of_utc",
        "experience_coverage_snapshots",
        ["as_of_utc"],
        schema=SCHEMA,
    )

    for table_name in (
        "pnl_attributions",
        "institutional_memories",
        "failure_archive_entries",
        "counterfactual_replays",
        "experience_coverage_snapshots",
    ):
        _immutable_trigger(table_name)


def downgrade() -> None:
    for table_name in (
        "experience_coverage_snapshots",
        "counterfactual_replays",
        "failure_archive_entries",
        "institutional_memories",
        "pnl_attributions",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON {SCHEMA}.{table_name}"
        )
        op.drop_table(table_name, schema=SCHEMA)
