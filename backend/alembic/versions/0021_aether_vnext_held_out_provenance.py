"""Bind held-out EvidenceWindow rows to immutable research provenance.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "held_out_evidence_provenance",
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.evidence_windows.evidence_window_id"),
            primary_key=True,
        ),
        sa.Column(
            "backtest_run_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.backtest_runs.backtest_run_id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.research_dataset_snapshots.dataset_snapshot_id"
            ),
            nullable=False,
        ),
        sa.Column("fold_result_ids", sa.JSON(), nullable=False),
        sa.Column("provenance_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_held_out_evidence_provenance_backtest_run_id",
        "held_out_evidence_provenance",
        ["backtest_run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_held_out_evidence_provenance_dataset_snapshot_id",
        "held_out_evidence_provenance",
        ["dataset_snapshot_id"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_held_out_evidence_provenance_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.held_out_evidence_provenance
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS "
        f"trg_held_out_evidence_provenance_immutable "
        f"ON {SCHEMA}.held_out_evidence_provenance"
    )
    op.drop_index(
        "ix_held_out_evidence_provenance_dataset_snapshot_id",
        table_name="held_out_evidence_provenance",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_held_out_evidence_provenance_backtest_run_id",
        table_name="held_out_evidence_provenance",
        schema=SCHEMA,
    )
    op.drop_table("held_out_evidence_provenance", schema=SCHEMA)
