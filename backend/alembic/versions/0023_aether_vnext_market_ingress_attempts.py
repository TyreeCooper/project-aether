"""Persist immutable provider-neutral market-ingress attempts.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "market_ingress_attempts",
        sa.Column("attempt_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("runtime_registry_binding_hash", sa.Text()),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("calendar_provider_id", sa.Text()),
        sa.Column(
            "observation_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.market_observations.observation_id"),
        ),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempted_sources", sa.JSON(), nullable=False),
        sa.Column("rejection_reasons", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_market_ingress_attempts_asset_id",
        "market_ingress_attempts",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_market_ingress_attempts_configuration_hash",
        "market_ingress_attempts",
        ["configuration_hash"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_market_ingress_attempts_as_of_utc",
        "market_ingress_attempts",
        ["as_of_utc"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_market_ingress_attempts_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.market_ingress_attempts
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_market_ingress_attempts_immutable "
        f"ON {SCHEMA}.market_ingress_attempts"
    )
    for index in (
        "ix_market_ingress_attempts_as_of_utc",
        "ix_market_ingress_attempts_configuration_hash",
        "ix_market_ingress_attempts_asset_id",
    ):
        op.drop_index(
            index,
            table_name="market_ingress_attempts",
            schema=SCHEMA,
        )
    op.drop_table("market_ingress_attempts", schema=SCHEMA)
