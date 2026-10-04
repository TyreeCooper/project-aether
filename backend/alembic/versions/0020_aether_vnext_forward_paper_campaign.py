"""Persist C9.1 forward-paper campaign baselines and evidence linkage.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def _immutable(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def upgrade() -> None:
    op.create_table(
        "forward_paper_campaigns",
        sa.Column("campaign_id", sa.Text(), primary_key=True),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("baseline_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forced_entry_enabled", sa.Boolean(), nullable=False),
        sa.Column("natural_setup_only", sa.Boolean(), nullable=False),
        sa.Column("real_market_time_required", sa.Boolean(), nullable=False),
        sa.Column("pit_inputs_required", sa.Boolean(), nullable=False),
        sa.Column("modeled_cost_capture_required", sa.Boolean(), nullable=False),
        sa.Column("observed_cost_capture_required", sa.Boolean(), nullable=False),
        sa.Column("route_pnl_accounting_required", sa.Boolean(), nullable=False),
        sa.Column("disposition_accounting_required", sa.Boolean(), nullable=False),
        sa.Column("no_cherry_pick", sa.Boolean(), nullable=False),
        sa.Column("historical_comparison_separate", sa.Boolean(), nullable=False),
        sa.Column("live_blocked", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "forced_entry_enabled = FALSE",
            name="ck_forward_campaign_forced_entry_off",
        ),
        sa.CheckConstraint(
            "natural_setup_only = TRUE "
            "AND real_market_time_required = TRUE "
            "AND pit_inputs_required = TRUE "
            "AND modeled_cost_capture_required = TRUE "
            "AND observed_cost_capture_required = TRUE "
            "AND route_pnl_accounting_required = TRUE "
            "AND disposition_accounting_required = TRUE "
            "AND no_cherry_pick = TRUE "
            "AND historical_comparison_separate = TRUE "
            "AND live_blocked = TRUE",
            name="ck_forward_campaign_c91_invariants",
        ),
        sa.CheckConstraint(
            "started_at_utc <= created_at_utc",
            name="ck_forward_campaign_time_order",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "forward_paper_campaign_routes",
        sa.Column("campaign_route_id", sa.Text(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.forward_paper_campaigns.campaign_id"),
            nullable=False,
        ),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("historical_validation_window_ids", sa.JSON(), nullable=False),
        sa.Column("historical_metrics_snapshot_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "campaign_id",
            "route_id",
            "playbook_id",
            name="uq_forward_campaign_route_playbook",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "forward_paper_campaign_windows",
        sa.Column("campaign_window_id", sa.Text(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.forward_paper_campaigns.campaign_id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_route_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.forward_paper_campaign_routes.campaign_route_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.evidence_windows.evidence_window_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("linked_at_utc", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    for table in (
        "forward_paper_campaigns",
        "forward_paper_campaign_routes",
        "forward_paper_campaign_windows",
    ):
        _immutable(table)


def downgrade() -> None:
    for table in (
        "forward_paper_campaign_windows",
        "forward_paper_campaign_routes",
        "forward_paper_campaigns",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}"
        )
        op.drop_table(table, schema=SCHEMA)
