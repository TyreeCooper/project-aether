"""Create isolated AETHER vNext persistence namespace.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25

This migration creates only the replacement runtime namespace and manifest table.
Legacy AETHER tables are intentionally untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "runtime_manifest",
        sa.Column("manifest_id", sa.Text(), primary_key=True),
        sa.Column("freeze_version", sa.Text(), nullable=False),
        sa.Column("spec_bundle", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("namespace_version", sa.Integer(), nullable=False),
        sa.Column("paper_only", sa.Boolean(), nullable=False),
        sa.Column("live_blocked", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_runtime_manifest_paper_only",
        "runtime_manifest",
        "paper_only IS TRUE",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_runtime_manifest_live_blocked",
        "runtime_manifest",
        "live_blocked IS TRUE",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("runtime_manifest", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
