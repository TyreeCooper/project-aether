"""Normalize multi-instrument sleeve inventory by broker account and asset.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-26

v4.2.1 names inventory_qty/inventory_avg on a broker sleeve, but one sleeve can
hold multiple instruments. Storing one scalar pair on Kraken or IBKR would mix
incompatible units. The normalized projection preserves those exact inventory
fields per (broker_account_id, asset_id).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    # There is no deployed vNext trading state yet. Refuse to guess an asset if a
    # development database somehow wrote scalar inventory before normalization.
    op.execute(
        sa.text(
            f"""
            DO $aether$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM {SCHEMA}.broker_account_ledgers
                    WHERE inventory_qty <> 0 OR inventory_avg IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'revision 0009 cannot infer asset_id from scalar sleeve inventory';
                END IF;
            END;
            $aether$;
            """
        )
    )

    op.create_table(
        "sleeve_inventory",
        sa.Column(
            "broker_account_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.broker_account_ledgers.broker_account_id"
            ),
            primary_key=True,
        ),
        sa.Column("asset_id", sa.Text(), primary_key=True),
        sa.Column("inventory_qty", sa.Float(), nullable=False),
        sa.Column("inventory_avg", sa.Float(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "inventory_qty > 0",
            name="ck_sleeve_inventory_qty_positive",
        ),
        sa.CheckConstraint(
            "inventory_avg > 0",
            name="ck_sleeve_inventory_avg_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_sleeve_inventory_version_positive",
        ),
        schema=SCHEMA,
    )

    op.drop_constraint(
        "ck_ledger_inventory_qty_nonnegative",
        "broker_account_ledgers",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column("broker_account_ledgers", "inventory_avg", schema=SCHEMA)
    op.drop_column("broker_account_ledgers", "inventory_qty", schema=SCHEMA)


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $aether$
            BEGIN
                IF EXISTS (SELECT 1 FROM {SCHEMA}.sleeve_inventory) THEN
                    RAISE EXCEPTION
                        'cannot downgrade revision 0009 with normalized inventory rows';
                END IF;
            END;
            $aether$;
            """
        )
    )

    op.add_column(
        "broker_account_ledgers",
        sa.Column("inventory_qty", sa.Float(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "broker_account_ledgers",
        sa.Column("inventory_avg", sa.Float(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_ledger_inventory_qty_nonnegative",
        "broker_account_ledgers",
        "inventory_qty >= 0",
        schema=SCHEMA,
    )
    op.drop_table("sleeve_inventory", schema=SCHEMA)
