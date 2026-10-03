"""Persist append-only F-006 research PromotionRecord history.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "research_promotions",
        sa.Column("promotion_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("from_evidence_state", sa.Text(), nullable=False),
        sa.Column("to_evidence_state", sa.Text(), nullable=False),
        sa.Column(
            "review_card_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.review_cards.review_card_id"),
            nullable=False,
        ),
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.evidence_windows.evidence_window_id"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("approver", sa.Text(), nullable=False),
        sa.Column("decided_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("n_reset", sa.Boolean(), nullable=False),
        sa.Column(
            "supersedes",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_promotions.promotion_id"),
        ),
        schema=SCHEMA,
    )
    for column in (
        "route_id",
        "review_card_id",
        "evidence_window_id",
        "decided_at_utc",
        "configuration_hash",
    ):
        op.create_index(
            f"ix_research_promotions_{column}",
            "research_promotions",
            [column],
            schema=SCHEMA,
        )
    op.execute(
        f"""
        CREATE TRIGGER trg_research_promotions_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.research_promotions
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_research_promotions_immutable "
        f"ON {SCHEMA}.research_promotions"
    )
    for column in reversed(
        (
            "route_id",
            "review_card_id",
            "evidence_window_id",
            "decided_at_utc",
            "configuration_hash",
        )
    ):
        op.drop_index(
            f"ix_research_promotions_{column}",
            table_name="research_promotions",
            schema=SCHEMA,
        )
    op.drop_table("research_promotions", schema=SCHEMA)
