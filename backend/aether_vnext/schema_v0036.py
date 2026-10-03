"""Revision-0036 metadata: independent AETHER Consensus Tape ledger."""
from __future__ import annotations

import sqlalchemy as sa

from aether_vnext.schema_v0035 import build_metadata as build_metadata_v0035


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = build_metadata_v0035(schema=schema)

    sa.Table(
        "tape_source_observations",
        md,
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("source_id", sa.Text(), nullable=False, index=True),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("source_symbol", sa.Text(), nullable=False),
        sa.Column("contract_id", sa.Text(), nullable=True),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("mark", sa.Float(), nullable=True),
        sa.Column("exchange_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_ms", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=False),
        sa.Column("source_data_version", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("age_ms >= 0", name="ck_tape_source_age_nonnegative"),
        sa.CheckConstraint(
            "bid IS NULL OR ask IS NULL OR bid <= ask",
            name="ck_tape_source_book_not_crossed",
        ),
    )
    sa.Index(
        "ix_tape_source_asset_received",
        md.tables[
            f"{schema}.tape_source_observations"
            if schema else "tape_source_observations"
        ].c.asset_id,
        md.tables[
            f"{schema}.tape_source_observations"
            if schema else "tape_source_observations"
        ].c.received_ts,
    )

    sa.Table(
        "tape_composites",
        md,
        sa.Column("composite_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("composite_mark", sa.Float(), nullable=True),
        sa.Column("median_mark", sa.Float(), nullable=True),
        sa.Column("accepted_source_ids", sa.JSON(), nullable=False),
        sa.Column("rejected_source_ids", sa.JSON(), nullable=False),
        sa.Column("source_observation_ids", sa.JSON(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("quorum_required", sa.Integer(), nullable=False),
        sa.Column("max_source_age_ms", sa.Integer(), nullable=True),
        sa.Column("agreement_bps", sa.Float(), nullable=True),
        sa.Column("provenance_complete", sa.Boolean(), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_count >= 0", name="ck_tape_composite_source_count"),
        sa.CheckConstraint(
            "quorum_required >= 1 AND quorum_required <= 5",
            name="ck_tape_composite_quorum",
        ),
        sa.CheckConstraint(
            "max_source_age_ms IS NULL OR max_source_age_ms >= 0",
            name="ck_tape_composite_age_nonnegative",
        ),
        sa.CheckConstraint(
            "agreement_bps IS NULL OR agreement_bps >= 0",
            name="ck_tape_composite_agreement_nonnegative",
        ),
    )
    sa.Index(
        "ix_tape_composite_asset_observed",
        md.tables[
            f"{schema}.tape_composites" if schema else "tape_composites"
        ].c.asset_id,
        md.tables[
            f"{schema}.tape_composites" if schema else "tape_composites"
        ].c.observed_at_utc,
    )
    return md


METADATA = build_metadata()
