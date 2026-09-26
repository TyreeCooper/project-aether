"""Add atomic Phase-6 Firm risk-admission capacity records.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "risk_admission_guard",
        sa.Column("scope_key", sa.Text(), primary_key=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_risk_admission_guard_version_positive",
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.risk_admission_guard
            (scope_key, row_version)
        VALUES ('firm', 1)
        ON CONFLICT (scope_key) DO NOTHING
        """
    )

    op.create_table(
        "risk_admission_reservations",
        sa.Column(
            "order_intent_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.order_intents.order_intent_id",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("cluster_id", sa.Text(), nullable=False, index=True),
        sa.Column("stop_risk_usd", sa.Float(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stop_risk_usd > 0",
            name="ck_risk_admission_stop_risk_positive",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("risk_admission_reservations", schema=SCHEMA)
    op.drop_table("risk_admission_guard", schema=SCHEMA)
