"""Persist configuration-isolated traffic experiments.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "traffic_experiments",
        sa.Column("experiment_id", sa.Text(), primary_key=True),
        sa.Column("change_family", sa.Text(), nullable=False),
        sa.Column(
            "control_configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column(
            "treatment_configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "control_configuration_hash <> treatment_configuration_hash",
            name="ck_traffic_experiment_distinct_configs",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "traffic_shadow_comparisons",
        sa.Column("shadow_comparison_id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.traffic_experiments.experiment_id"),
            nullable=False,
        ),
        sa.Column("opportunity_id", sa.Text(), nullable=False),
        sa.Column("current_configuration_hash", sa.Text(), nullable=False),
        sa.Column("prior_configuration_hash", sa.Text(), nullable=False),
        sa.Column("would_pass_under_prior_policy", sa.Boolean(), nullable=False),
        sa.Column("order_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evaluated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "order_created = FALSE",
            name="ck_shadow_comparison_no_order",
        ),
        sa.CheckConstraint(
            "current_configuration_hash <> prior_configuration_hash",
            name="ck_shadow_comparison_distinct_configs",
        ),
        schema=SCHEMA,
    )
    for table in ("traffic_experiments", "traffic_shadow_comparisons"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
            """
        )


def downgrade() -> None:
    for table in ("traffic_shadow_comparisons", "traffic_experiments"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}"
        )
        op.drop_table(table, schema=SCHEMA)
