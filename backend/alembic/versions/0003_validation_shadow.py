"""validation and shadow ledgers

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "venue_validation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("venue", sa.String(length=32), nullable=False),
        sa.Column("client_order_id", sa.String(length=96), nullable=False, unique=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=False, unique=True),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_venue_validation_events_created_at",
        "venue_validation_events",
        ["created_at"],
    )
    op.create_index(
        "ix_venue_validation_events_symbol",
        "venue_validation_events",
        ["symbol"],
    )

    op.create_table(
        "shadow_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("mark", sa.Float(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("in_position", sa.Boolean(), nullable=False),
        sa.Column("would_execute", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=96), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_shadow_decisions_created_at", "shadow_decisions", ["created_at"])
    op.create_index("ix_shadow_decisions_signal", "shadow_decisions", ["signal"])


def downgrade() -> None:
    op.drop_index("ix_shadow_decisions_signal", table_name="shadow_decisions")
    op.drop_index("ix_shadow_decisions_created_at", table_name="shadow_decisions")
    op.drop_table("shadow_decisions")
    op.drop_index(
        "ix_venue_validation_events_symbol",
        table_name="venue_validation_events",
    )
    op.drop_index(
        "ix_venue_validation_events_created_at",
        table_name="venue_validation_events",
    )
    op.drop_table("venue_validation_events")
