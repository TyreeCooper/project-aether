"""Persist append-only intelligence shadow audit records.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "intelligence_shadow_audits",
        sa.Column("audit_id", sa.Text(), primary_key=True),
        sa.Column("opportunity_id", sa.Text(), nullable=False),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_configuration_hash", sa.Text(), nullable=False),
        sa.Column("shadow_configuration_hash", sa.Text(), nullable=False),
        sa.Column("enabled_components", sa.JSON(), nullable=False),
        sa.Column("baseline_outcome", sa.Text(), nullable=False),
        sa.Column("shadow_outcome", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("order_created", sa.Boolean(), nullable=False),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_intelligence_shadow_audit_research_only",
        ),
        sa.CheckConstraint(
            "order_created = false",
            name="ck_intelligence_shadow_audit_no_order",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_intelligence_shadow_audit_no_trade_influence",
        ),
        schema=SCHEMA,
    )
    for column in ("opportunity_id", "route_id", "as_of_utc"):
        op.create_index(
            f"ix_intelligence_shadow_audits_{column}",
            "intelligence_shadow_audits",
            [column],
            schema=SCHEMA,
        )
    op.execute(
        f"""
        CREATE TRIGGER trg_intelligence_shadow_audits_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.intelligence_shadow_audits
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_intelligence_shadow_audits_immutable "
        f"ON {SCHEMA}.intelligence_shadow_audits"
    )
    op.drop_table("intelligence_shadow_audits", schema=SCHEMA)
