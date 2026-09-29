"""Add immutable paper-test epoch boundaries.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "paper_test_epochs",
        sa.Column("epoch_id", sa.Text(), primary_key=True),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("prior_state_hash", sa.Text(), nullable=False),
        sa.Column("seed_sleeves", sa.JSON(), nullable=False),
        sa.Column("seed_bank_total_usd", sa.Float(), nullable=False),
        sa.Column("paper_only", sa.Boolean(), nullable=False),
        sa.Column("live_blocked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("started_at_utc", name="uq_paper_test_epoch_started_at"),
        sa.CheckConstraint("seed_bank_total_usd > 0", name="ck_paper_test_epoch_seed_positive"),
        sa.CheckConstraint("started_at_utc <= created_at_utc", name="ck_paper_test_epoch_time_order"),
        sa.CheckConstraint("paper_only = true AND live_blocked = true", name="ck_paper_test_epoch_safety"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_paper_test_epochs_started_at_utc",
        "paper_test_epochs",
        ["started_at_utc"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_paper_test_epochs_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.paper_test_epochs
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_paper_test_epochs_immutable ON {SCHEMA}.paper_test_epochs"
    )
    op.drop_table("paper_test_epochs", schema=SCHEMA)
