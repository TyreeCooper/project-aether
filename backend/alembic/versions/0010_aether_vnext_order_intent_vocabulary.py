"""Normalize OrderIntent to exact v4.2.1 binding field names.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


RENAMES = (
    ("symbol", "symbol_executed"),
    ("qty", "requested_qty"),
    ("expected_fill", "expected_fill_price"),
    ("slippage_usd", "slip_usd"),
    ("slippage_bps", "slip_bps"),
    ("market_observation_id", "observation_id_at_reserve"),
    ("fill_market_observation_id", "observation_id_at_fill"),
    ("row_version", "version"),
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_order_intent_qty_positive",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_order_intent_row_version_positive",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    for old_name, new_name in RENAMES:
        op.alter_column(
            "order_intents",
            old_name,
            new_column_name=new_name,
            schema=SCHEMA,
        )
    op.create_check_constraint(
        "ck_order_intent_requested_qty_positive",
        "order_intents",
        "requested_qty > 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_order_intent_version_positive",
        "order_intents",
        "version >= 1",
        schema=SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.order_intents
        SET order_type = 'MARKET_PAPER'
        WHERE order_type IN ('market', 'MARKET', 'MARKET_PAPER')
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_intent_version_positive",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_order_intent_requested_qty_positive",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    for old_name, new_name in reversed(RENAMES):
        op.alter_column(
            "order_intents",
            new_name,
            new_column_name=old_name,
            schema=SCHEMA,
        )
    op.create_check_constraint(
        "ck_order_intent_qty_positive",
        "order_intents",
        "qty > 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_order_intent_row_version_positive",
        "order_intents",
        "row_version >= 1",
        schema=SCHEMA,
    )
