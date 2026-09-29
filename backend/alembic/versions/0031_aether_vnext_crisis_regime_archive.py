"""Persist Phase-14 historical crisis/regime archive.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"

CRISIS_REGIME_CATEGORY_SQL = (
    "category IN ("
    "'crash_flash_crash',"
    "'volatility_expansion_compression',"
    "'liquidity_crisis',"
    "'rate_inflation_shock',"
    "'geopolitical_shock',"
    "'bank_exchange_failure',"
    "'commodity_shock',"
    "'earnings_guidance_gap',"
    "'regulatory_shock',"
    "'crypto_failure_venue_incident',"
    "'policy_reversal',"
    "'scheduled_macro_surprise'"
    ")"
)


def upgrade() -> None:
    op.create_table(
        "crisis_regime_archive_entries",
        sa.Column("archive_id", sa.Text(), primary_key=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("episode_ref", sa.Text(), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("regime_ids", sa.JSON(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_ids", sa.JSON(), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            CRISIS_REGIME_CATEGORY_SQL,
            name="ck_crisis_regime_archive_category",
        ),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_crisis_regime_archive_research_only",
        ),
        sa.CheckConstraint(
            "ended_at_utc >= started_at_utc",
            name="ck_crisis_regime_archive_time_order",
        ),
        sa.CheckConstraint(
            "recorded_at_utc >= started_at_utc",
            name="ck_crisis_regime_archive_recorded_order",
        ),
        schema=SCHEMA,
    )
    for column in (
        "category",
        "started_at_utc",
        "recorded_at_utc",
    ):
        op.create_index(
            f"ix_crisis_regime_archive_entries_{column}",
            "crisis_regime_archive_entries",
            [column],
            schema=SCHEMA,
        )

    op.execute(
        f"""
        CREATE TRIGGER trg_crisis_regime_archive_entries_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.crisis_regime_archive_entries
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_crisis_regime_archive_entries_immutable "
        f"ON {SCHEMA}.crisis_regime_archive_entries"
    )
    op.drop_table("crisis_regime_archive_entries", schema=SCHEMA)
