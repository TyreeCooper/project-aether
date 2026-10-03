"""Add independent AETHER Consensus Tape persistence.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "tape_source_observations",
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
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
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tape_source_observations_asset_id",
        "tape_source_observations",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tape_source_observations_source_id",
        "tape_source_observations",
        ["source_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tape_source_asset_received",
        "tape_source_observations",
        ["asset_id", "received_ts"],
        schema=SCHEMA,
    )

    op.create_table(
        "tape_composites",
        sa.Column("composite_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
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
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tape_composites_asset_id",
        "tape_composites",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tape_composite_asset_observed",
        "tape_composites",
        ["asset_id", "observed_at_utc"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tape_composite_asset_observed",
        table_name="tape_composites",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_tape_composites_asset_id",
        table_name="tape_composites",
        schema=SCHEMA,
    )
    op.drop_table("tape_composites", schema=SCHEMA)
    op.drop_index(
        "ix_tape_source_asset_received",
        table_name="tape_source_observations",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_tape_source_observations_source_id",
        table_name="tape_source_observations",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_tape_source_observations_asset_id",
        table_name="tape_source_observations",
        schema=SCHEMA,
    )
    op.drop_table("tape_source_observations", schema=SCHEMA)
