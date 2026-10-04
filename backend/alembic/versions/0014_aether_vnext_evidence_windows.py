"""Persist immutable, non-mixable EvidenceWindow domains.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "evidence_windows",
        sa.Column("evidence_window_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.policy_snapshots.configuration_hash"
            ),
            nullable=False,
        ),
        sa.Column("sample_domain", sa.Text(), nullable=False),
        sa.Column(
            "first_timestamp_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_timestamp_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("immutable_trade_ids", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "n > 0",
            name="ck_evidence_windows_n_positive",
        ),
        sa.CheckConstraint(
            "first_timestamp_utc <= last_timestamp_utc",
            name="ck_evidence_windows_timestamp_order",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_evidence_windows_route_id",
        "evidence_windows",
        ["route_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_evidence_windows_configuration_hash",
        "evidence_windows",
        ["configuration_hash"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_evidence_windows_sample_domain",
        "evidence_windows",
        ["sample_domain"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_evidence_windows_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.evidence_windows
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_evidence_windows_immutable "
        f"ON {SCHEMA}.evidence_windows"
    )
    op.drop_index(
        "ix_evidence_windows_sample_domain",
        table_name="evidence_windows",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_evidence_windows_configuration_hash",
        table_name="evidence_windows",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_evidence_windows_route_id",
        table_name="evidence_windows",
        schema=SCHEMA,
    )
    op.drop_table("evidence_windows", schema=SCHEMA)
