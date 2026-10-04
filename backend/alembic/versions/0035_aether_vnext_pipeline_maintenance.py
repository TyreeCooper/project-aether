"""Add AETHER Pipeline Maintenance controls and incident history.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-02
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
SCHEMA = "aether_vnext"

def upgrade() -> None:
    op.create_table(
        "maintenance_controls",
        sa.Column("control_key", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("row_version > 0", name="ck_maintenance_control_row_version_positive"),
        schema=SCHEMA,
    )
    op.create_table(
        "maintenance_incidents",
        sa.Column("incident_id", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("diagnosis", sa.JSON(), nullable=False),
        sa.Column("repair", sa.JSON(), nullable=False),
        sa.Column("first_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recurrence_count", sa.Integer(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.CheckConstraint("affected_count >= 0", name="ck_maintenance_incident_affected_nonnegative"),
        sa.CheckConstraint("recurrence_count > 0", name="ck_maintenance_incident_recurrence_positive"),
        schema=SCHEMA,
    )

def downgrade() -> None:
    op.drop_table("maintenance_incidents", schema=SCHEMA)
    op.drop_table("maintenance_controls", schema=SCHEMA)
