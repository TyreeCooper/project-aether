"""Persist immutable point-in-time research OHLCV bars.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "research_bars",
        sa.Column("research_bar_id", sa.Text(), primary_key=True),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.research_dataset_snapshots.dataset_snapshot_id"
            ),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("bucket_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_data_version", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("available_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "dataset_snapshot_id",
            "asset_id",
            "interval_seconds",
            "bucket_open_utc",
            name="uq_research_bar_dataset_asset_interval_open",
        ),
        sa.CheckConstraint(
            "interval_seconds > 0",
            name="ck_research_bar_interval_positive",
        ),
        sa.CheckConstraint(
            "bucket_open_utc < bucket_close_utc",
            name="ck_research_bar_window_order",
        ),
        sa.CheckConstraint(
            "available_at_utc >= bucket_close_utc",
            name="ck_research_bar_available_after_close",
        ),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="ck_research_bar_prices_positive",
        ),
        sa.CheckConstraint(
            "high >= open AND high >= close AND high >= low",
            name="ck_research_bar_high_consistent",
        ),
        sa.CheckConstraint(
            "low <= open AND low <= close AND low <= high",
            name="ck_research_bar_low_consistent",
        ),
        sa.CheckConstraint(
            "volume >= 0",
            name="ck_research_bar_volume_nonnegative",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_research_bars_dataset_snapshot_id",
        "research_bars",
        ["dataset_snapshot_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_research_bars_asset_id",
        "research_bars",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_research_bars_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.research_bars
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_research_bars_immutable "
        f"ON {SCHEMA}.research_bars"
    )
    op.drop_index(
        "ix_research_bars_asset_id",
        table_name="research_bars",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_research_bars_dataset_snapshot_id",
        table_name="research_bars",
        schema=SCHEMA,
    )
    op.drop_table("research_bars", schema=SCHEMA)
