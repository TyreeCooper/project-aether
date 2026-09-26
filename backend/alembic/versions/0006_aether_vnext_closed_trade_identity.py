"""Make ClosedTrade self-contained execution evidence.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    for column in (
        sa.Column("asset_id", sa.Text(), nullable=True),
        sa.Column("position_key", sa.Text(), nullable=True),
        sa.Column("side", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("avg_entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("fees_usd", sa.Float(), nullable=True),
    ):
        op.add_column("closed_trades", column, schema=SCHEMA)

    # Existing vNext paper rows are not expected before cutover. If a development
    # database already contains a ClosedTrade, backfill immutable OPEN identity
    # from its referenced OpenTrade. Exit-only fields cannot be guessed.
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.closed_trades AS c
            SET
                asset_id = o.asset_id,
                position_key = o.position_key,
                side = o.side,
                quantity = o.quantity,
                avg_entry_price = o.avg_entry_price
            FROM {SCHEMA}.open_trades AS o
            WHERE c.trade_id = o.trade_id
            """
        )
    )

    # No pre-0006 row can truthfully supply exit_price or fees_usd. Refuse to
    # silently manufacture evidence if such development rows exist.
    op.execute(
        sa.text(
            f"""
            DO $aether$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM {SCHEMA}.closed_trades
                    WHERE exit_price IS NULL OR fees_usd IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'revision 0006 requires explicit exit_price and fees_usd for existing ClosedTrade rows';
                END IF;
            END;
            $aether$;
            """
        )
    )

    for name in (
        "asset_id",
        "position_key",
        "side",
        "quantity",
        "avg_entry_price",
        "exit_price",
        "fees_usd",
    ):
        op.alter_column(
            "closed_trades",
            name,
            nullable=False,
            schema=SCHEMA,
        )

    op.create_index(
        "ix_closed_trades_asset_id",
        "closed_trades",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_closed_trades_position_key",
        "closed_trades",
        ["position_key"],
        schema=SCHEMA,
    )

    op.create_check_constraint(
        "ck_closed_trade_quantity_positive",
        "closed_trades",
        "quantity > 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_closed_trade_entry_positive",
        "closed_trades",
        "avg_entry_price > 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_closed_trade_exit_positive",
        "closed_trades",
        "exit_price > 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_closed_trade_fees_nonnegative",
        "closed_trades",
        "fees_usd >= 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    for constraint in (
        "ck_closed_trade_fees_nonnegative",
        "ck_closed_trade_exit_positive",
        "ck_closed_trade_entry_positive",
        "ck_closed_trade_quantity_positive",
    ):
        op.drop_constraint(
            constraint,
            "closed_trades",
            type_="check",
            schema=SCHEMA,
        )

    op.drop_index(
        "ix_closed_trades_position_key",
        table_name="closed_trades",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_closed_trades_asset_id",
        table_name="closed_trades",
        schema=SCHEMA,
    )

    for name in (
        "fees_usd",
        "exit_price",
        "avg_entry_price",
        "quantity",
        "side",
        "position_key",
        "asset_id",
    ):
        op.drop_column("closed_trades", name, schema=SCHEMA)
