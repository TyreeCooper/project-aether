"""Freeze runtime Product Registry binding identity on campaign routes.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.add_column(
        "forward_paper_campaign_routes",
        sa.Column(
            "runtime_registry_binding_hash",
            sa.Text(),
            nullable=False,
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(
        "forward_paper_campaign_routes",
        "runtime_registry_binding_hash",
        schema=SCHEMA,
    )
