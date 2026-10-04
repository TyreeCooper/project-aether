"""FROZEN revision-0026 SQLAlchemy metadata for AETHER vNext.

Revision 0026 adds the append-only F-006 research PromotionRecord ledger while
preserving every table from revision 0025.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0025 import build_metadata as build_metadata_v0025


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0025(schema=schema)

    sa.Table(
        "research_promotions",
        md,
        sa.Column("promotion_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("from_evidence_state", sa.Text(), nullable=False),
        sa.Column("to_evidence_state", sa.Text(), nullable=False),
        sa.Column(
            "review_card_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "review_cards.review_card_id")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "evidence_windows.evidence_window_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("approver", sa.Text(), nullable=False),
        sa.Column("decided_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("n_reset", sa.Boolean(), nullable=False),
        sa.Column(
            "supersedes",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_promotions.promotion_id")),
        ),
    )
    return md


def _fk(schema: str | None, target: str) -> str:
    return f"{schema}.{target}" if schema else target


METADATA = build_metadata()
