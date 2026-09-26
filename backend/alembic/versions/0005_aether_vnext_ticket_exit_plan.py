"""Bind READY tickets to a frozen ExitPlan identity.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("exit_plan_id", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_tickets_exit_plan",
        "tickets",
        "exit_plans",
        ["exit_plan_id"],
        ["exit_plan_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tickets_exit_plan",
        "tickets",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_column("tickets", "exit_plan_id", schema=SCHEMA)
