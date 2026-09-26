"""Persist immutable P11 profitability-readiness burn-in assessments.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "profitability_readiness_assessments",
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("readiness_policy_version", sa.Text(), nullable=False),
        sa.Column("firm_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("burn_in_start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burn_in_end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burn_in_duration_s", sa.Float(), nullable=False),
        sa.Column("active_route_count", sa.Integer(), nullable=False),
        sa.Column("trusted_route_count", sa.Integer(), nullable=False),
        sa.Column("oos_positive_route_count", sa.Integer(), nullable=False),
        sa.Column("sustained_operation_satisfied", sa.Boolean()),
        sa.Column("sustained_operation_policy_version", sa.Text()),
        sa.Column("oos_trusted_sufficiency_satisfied", sa.Boolean()),
        sa.Column("oos_trusted_sufficiency_policy_version", sa.Text()),
        sa.Column("profitability_ready", sa.Boolean(), nullable=False),
        sa.Column(
            "live_execution_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("unresolved_rules", sa.JSON(), nullable=False),
        sa.Column("unresolved_accounting_defects", sa.JSON(), nullable=False),
        sa.Column("unresolved_model_defects", sa.JSON(), nullable=False),
        sa.Column("evidence_checks", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "burn_in_start_at_utc <= burn_in_end_at_utc "
            "AND burn_in_end_at_utc <= as_of_utc",
            name="ck_profitability_readiness_time_order",
        ),
        sa.CheckConstraint(
            "active_route_count >= 0 "
            "AND trusted_route_count >= 0 "
            "AND oos_positive_route_count >= 0",
            name="ck_profitability_readiness_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "trusted_route_count <= active_route_count "
            "AND oos_positive_route_count <= active_route_count",
            name="ck_profitability_readiness_route_counts",
        ),
        sa.CheckConstraint(
            "live_execution_authorized = FALSE",
            name="ck_profitability_readiness_never_live_authority",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profitability_readiness_firm_snapshot_hash",
        "profitability_readiness_assessments",
        ["firm_snapshot_hash"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_profitability_readiness_assessments_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.profitability_readiness_assessments
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_profitability_readiness_assessments_immutable "
        f"ON {SCHEMA}.profitability_readiness_assessments"
    )
    op.drop_index(
        "ix_profitability_readiness_firm_snapshot_hash",
        table_name="profitability_readiness_assessments",
        schema=SCHEMA,
    )
    op.drop_table("profitability_readiness_assessments", schema=SCHEMA)
