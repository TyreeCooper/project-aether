"""Add isolated prototype market-bar ledger.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "prototype_market_bars",
        sa.Column("bar_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("bucket_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("available_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_id",
            "interval_seconds",
            "bucket_open_utc",
            "source_id",
            name="uq_prototype_market_bar_identity",
        ),
        sa.CheckConstraint("interval_seconds > 0", name="ck_prototype_bar_interval_positive"),
        sa.CheckConstraint("bucket_close_utc > bucket_open_utc", name="ck_prototype_bar_time_order"),
        sa.CheckConstraint("available_at_utc >= bucket_close_utc", name="ck_prototype_bar_available_after_close"),
        sa.CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_prototype_bar_prices_positive"),
        sa.CheckConstraint("high >= low", name="ck_prototype_bar_high_low"),
        sa.CheckConstraint("volume >= 0", name="ck_prototype_bar_volume_nonnegative"),
        sa.CheckConstraint("trade_count >= 0", name="ck_prototype_bar_trade_count_nonnegative"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prototype_market_bars_asset_id",
        "prototype_market_bars",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prototype_market_bars_asset_interval_close",
        "prototype_market_bars",
        ["asset_id", "interval_seconds", "bucket_close_utc"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_prototype_market_bars_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.prototype_market_bars
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_prototype_market_bars_immutable "
        f"ON {SCHEMA}.prototype_market_bars"
    )
    op.drop_table("prototype_market_bars", schema=SCHEMA)
