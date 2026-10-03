"""Persist immutable ProfitabilityEvidence and Review linkage.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "profitability_evidence",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
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
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("fill_model_version", sa.Text(), nullable=False),
        sa.Column("fee_schedule_version", sa.Text(), nullable=False),
        sa.Column("in_sample_window", sa.JSON()),
        sa.Column("oos_windows", sa.JSON(), nullable=False),
        sa.Column("n_trades", sa.Integer(), nullable=False),
        sa.Column("net_expectancy_usd", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_win_usd", sa.Float(), nullable=False),
        sa.Column("avg_loss_usd", sa.Float(), nullable=False),
        sa.Column("stop_rate", sa.Float(), nullable=False),
        sa.Column("max_drawdown_usd", sa.Float(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("median_duration_s", sa.Float(), nullable=False),
        sa.Column("capture_efficiency", sa.Float(), nullable=False),
        sa.Column("cost_sensitivity", sa.JSON(), nullable=False),
        sa.Column("regime_matrix", sa.JSON(), nullable=False),
        sa.Column("benchmark_result", sa.JSON(), nullable=False),
        sa.Column("capacity_result", sa.JSON(), nullable=False),
        sa.Column("portfolio_contribution", sa.JSON(), nullable=False),
        sa.Column("model_risks", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "n_trades >= 0",
            name="ck_profitability_evidence_n_nonnegative",
        ),
        sa.CheckConstraint(
            "win_rate >= 0 AND win_rate <= 1",
            name="ck_profitability_evidence_win_rate_unit",
        ),
        sa.CheckConstraint(
            "stop_rate >= 0 AND stop_rate <= 1",
            name="ck_profitability_evidence_stop_rate_unit",
        ),
        sa.CheckConstraint(
            "median_duration_s >= 0",
            name="ck_profitability_evidence_duration_nonnegative",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profitability_evidence_route_id",
        "profitability_evidence",
        ["route_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profitability_evidence_configuration_hash",
        "profitability_evidence",
        ["configuration_hash"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_review_cards_profitability_evidence",
        "review_cards",
        "profitability_evidence",
        ["evidence_id"],
        ["evidence_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_profitability_evidence_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.profitability_evidence
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_profitability_evidence_immutable "
        f"ON {SCHEMA}.profitability_evidence"
    )
    op.drop_constraint(
        "fk_review_cards_profitability_evidence",
        "review_cards",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_profitability_evidence_configuration_hash",
        table_name="profitability_evidence",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_profitability_evidence_route_id",
        table_name="profitability_evidence",
        schema=SCHEMA,
    )
    op.drop_table("profitability_evidence", schema=SCHEMA)
