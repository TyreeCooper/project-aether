"""Revision-0035 metadata: AETHER Pipeline Maintenance control plane."""
from __future__ import annotations
import sqlalchemy as sa
from aether_vnext.schema_v0033 import build_metadata as build_metadata_v0033

def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0033(schema=schema)
    sa.Table(
        "maintenance_controls", md,
        sa.Column("control_key", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("row_version > 0", name="ck_maintenance_control_row_version_positive"),
    )
    sa.Table(
        "maintenance_incidents", md,
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
    )
    return md

METADATA = build_metadata()
