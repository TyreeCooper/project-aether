"""FROZEN revision-0029 SQLAlchemy metadata for AETHER vNext.

Revision 0029 adds append-only Phase-13 intelligence shadow audit records while
preserving every table from revision 0028.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0028 import build_metadata as build_metadata_v0028


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0028(schema=schema)

    sa.Table(
        "intelligence_shadow_audits",
        md,
        sa.Column("audit_id", sa.Text(), primary_key=True),
        sa.Column("opportunity_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("baseline_configuration_hash", sa.Text(), nullable=False),
        sa.Column("shadow_configuration_hash", sa.Text(), nullable=False),
        sa.Column("enabled_components", sa.JSON(), nullable=False),
        sa.Column("baseline_outcome", sa.Text(), nullable=False),
        sa.Column("shadow_outcome", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("order_created", sa.Boolean(), nullable=False),
        sa.Column("trade_influence_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "research_only = true",
            name="ck_intelligence_shadow_audit_research_only",
        ),
        sa.CheckConstraint(
            "order_created = false",
            name="ck_intelligence_shadow_audit_no_order",
        ),
        sa.CheckConstraint(
            "trade_influence_enabled = false",
            name="ck_intelligence_shadow_audit_no_trade_influence",
        ),
    )
    return md


METADATA = build_metadata()
