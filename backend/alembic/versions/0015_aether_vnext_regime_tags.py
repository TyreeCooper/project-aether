"""Add point-in-time regime tags to Setup and ClosedTrade evidence.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.add_column(
        "setups",
        sa.Column("regime_tags", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "closed_trades",
        sa.Column("regime_tags", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_setup_regime_mutation()
        RETURNS trigger AS $aether$
        BEGIN
            IF OLD.regime_tags IS DISTINCT FROM NEW.regime_tags THEN
                RAISE EXCEPTION 'Setup regime tags are immutable';
            END IF;
            RETURN NEW;
        END;
        $aether$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_setup_regime_tags_immutable
        BEFORE UPDATE ON {SCHEMA}.setups
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_setup_regime_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_setup_regime_tags_immutable "
        f"ON {SCHEMA}.setups"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_setup_regime_mutation()"
    )
    op.drop_column("closed_trades", "regime_tags", schema=SCHEMA)
    op.drop_column("setups", "regime_tags", schema=SCHEMA)
