"""FROZEN revision-0032 SQLAlchemy metadata for AETHER vNext.

Revision 0032 adds immutable paper-test epoch boundaries so a new test run can
start with fresh paper capital and an empty epoch-scoped blotter without deleting
prior trade history or research evidence.
"""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0031 import build_metadata as build_metadata_v0031


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0031(schema=schema)

    sa.Table(
        "paper_test_epochs",
        md,
        sa.Column("epoch_id", sa.Text(), primary_key=True),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False, unique=True, index=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("prior_state_hash", sa.Text(), nullable=False),
        sa.Column("seed_sleeves", sa.JSON(), nullable=False),
        sa.Column("seed_bank_total_usd", sa.Float(), nullable=False),
        sa.Column("paper_only", sa.Boolean(), nullable=False),
        sa.Column("live_blocked", sa.Boolean(), nullable=False),
        sa.CheckConstraint("seed_bank_total_usd > 0", name="ck_paper_test_epoch_seed_positive"),
        sa.CheckConstraint("started_at_utc <= created_at_utc", name="ck_paper_test_epoch_time_order"),
        sa.CheckConstraint("paper_only = true AND live_blocked = true", name="ck_paper_test_epoch_safety"),
    )
    return md


METADATA = build_metadata()
