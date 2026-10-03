"""Add execution-reservation fields required by AETHER vNext Phase 5.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.add_column(
        "order_intents",
        sa.Column("broker_account_id", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.order_intents
            SET broker_account_id = CASE
                WHEN broker = 'Kraken' THEN 'kraken_paper'
                WHEN broker = 'tastyfx' THEN 'tastyfx_paper'
                WHEN broker = 'NinjaTrader' THEN 'ninja_paper'
                WHEN broker = 'IBKR' THEN 'ibkr_paper'
                ELSE broker_account_id
            END
            WHERE broker_account_id IS NULL
            """
        )
    )
    op.alter_column(
        "order_intents",
        "broker_account_id",
        nullable=False,
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_order_intents_broker_account",
        "order_intents",
        "broker_account_ledgers",
        ["broker_account_id"],
        ["broker_account_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    op.add_column(
        "order_intents",
        sa.Column("exit_plan_id", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_order_intents_exit_plan",
        "order_intents",
        "exit_plans",
        ["exit_plan_id"],
        ["exit_plan_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    op.add_column(
        "order_intents",
        sa.Column("intent_kind", sa.Text(), nullable=False, server_default="OPEN"),
        schema=SCHEMA,
    )
    op.add_column("order_intents", sa.Column("position_key", sa.Text()), schema=SCHEMA)
    op.add_column("order_intents", sa.Column("signal_key", sa.Text()), schema=SCHEMA)
    op.add_column(
        "order_intents",
        sa.Column("reserved_cash_usd", sa.Float(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "order_intents",
        sa.Column("reserved_margin_usd", sa.Float(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column("order_intents", sa.Column("ready_spread_bps", sa.Float()), schema=SCHEMA)
    op.add_column("order_intents", sa.Column("hard_stop_price", sa.Float()), schema=SCHEMA)
    op.add_column(
        "order_intents",
        sa.Column("submit_timeout_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.add_column(
        "order_intents",
        sa.Column("fill_market_observation_id", sa.Text()),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_order_intents_fill_market_observation",
        "order_intents",
        "market_observations",
        ["fill_market_observation_id"],
        ["observation_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.add_column("order_intents", sa.Column("trade_id", sa.Text()), schema=SCHEMA)
    op.add_column(
        "order_intents",
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_order_intents_position_key",
        "order_intents",
        ["position_key"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_order_intents_signal_key",
        "order_intents",
        ["signal_key"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_order_intents_trade_id",
        "order_intents",
        ["trade_id"],
        schema=SCHEMA,
    )

    op.create_check_constraint(
        "ck_order_intent_reserved_cash_nonnegative",
        "order_intents",
        "reserved_cash_usd >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_order_intent_reserved_margin_nonnegative",
        "order_intents",
        "reserved_margin_usd >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_order_intent_row_version_positive",
        "order_intents",
        "row_version >= 1",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_intent_row_version_positive",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_order_intent_reserved_margin_nonnegative",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_order_intent_reserved_cash_nonnegative",
        "order_intents",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_index("ix_order_intents_trade_id", table_name="order_intents", schema=SCHEMA)
    op.drop_index("ix_order_intents_signal_key", table_name="order_intents", schema=SCHEMA)
    op.drop_index("ix_order_intents_position_key", table_name="order_intents", schema=SCHEMA)

    op.drop_constraint(
        "fk_order_intents_fill_market_observation",
        "order_intents",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_order_intents_exit_plan",
        "order_intents",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_order_intents_broker_account",
        "order_intents",
        type_="foreignkey",
        schema=SCHEMA,
    )

    for column in (
        "row_version",
        "trade_id",
        "fill_market_observation_id",
        "submit_timeout_at",
        "hard_stop_price",
        "ready_spread_bps",
        "reserved_margin_usd",
        "reserved_cash_usd",
        "signal_key",
        "position_key",
        "intent_kind",
        "exit_plan_id",
        "broker_account_id",
    ):
        op.drop_column("order_intents", column, schema=SCHEMA)
