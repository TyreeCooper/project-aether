"""Add complete v4.2.1 sleeve-ledger fields.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
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
    op.add_column(
        "broker_account_ledgers",
        sa.Column("carry_accrued_usd", sa.Float(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_ledger_inventory_qty_nonnegative",
        "broker_account_ledgers",
        "inventory_qty >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_ledger_carry_nonnegative",
        "broker_account_ledgers",
        "carry_accrued_usd >= 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ledger_carry_nonnegative",
        "broker_account_ledgers",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_ledger_inventory_qty_nonnegative",
        "broker_account_ledgers",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column("broker_account_ledgers", "carry_accrued_usd", schema=SCHEMA)
    op.drop_column("broker_account_ledgers", "inventory_avg", schema=SCHEMA)
    op.drop_column("broker_account_ledgers", "inventory_qty", schema=SCHEMA)
