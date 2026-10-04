"""Persist immutable edge-decay Review requests.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "decay_review_requests",
        sa.Column("decay_request_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.policy_snapshots.configuration_hash"
            ),
            nullable=False,
        ),
        sa.Column(
            "reference_evidence_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.profitability_evidence.evidence_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "recent_evidence_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.profitability_evidence.evidence_id"
            ),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_review", sa.Boolean(), nullable=False),
        sa.Column("materiality_decision", sa.Boolean()),
        sa.Column("materiality_policy_version", sa.Text()),
        sa.Column("metric_deltas", sa.JSON(), nullable=False),
        sa.Column("deterioration_dimensions", sa.JSON(), nullable=False),
        sa.Column("unresolved_rules", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reference_evidence_id <> recent_evidence_id",
            name="ck_decay_reference_recent_distinct",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_decay_review_requests_route_id",
        "decay_review_requests",
        ["route_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_decay_review_requests_configuration_hash",
        "decay_review_requests",
        ["configuration_hash"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_decay_review_requests_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.decay_review_requests
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_decay_review_requests_immutable "
        f"ON {SCHEMA}.decay_review_requests"
    )
    op.drop_index(
        "ix_decay_review_requests_configuration_hash",
        table_name="decay_review_requests",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_decay_review_requests_route_id",
        table_name="decay_review_requests",
        schema=SCHEMA,
    )
    op.drop_table("decay_review_requests", schema=SCHEMA)
