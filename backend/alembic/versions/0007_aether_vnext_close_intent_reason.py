"""Persist CLOSE intent exit reason for crash-safe flatten recovery.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.add_column(
        "order_intents",
        sa.Column("exit_reason", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("order_intents", "exit_reason", schema=SCHEMA)
