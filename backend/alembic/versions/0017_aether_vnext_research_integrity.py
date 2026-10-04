"""Persist the F-006 research integrity ledger.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def _immutable(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def upgrade() -> None:
    op.create_table(
        "research_hypotheses",
        sa.Column("hypothesis_id", sa.Text(), primary_key=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hypothesis_text", sa.Text(), nullable=False),
        sa.Column("economic_rationale", sa.Text(), nullable=False),
        sa.Column("mechanism_class", sa.Text(), nullable=False),
        sa.Column("eligible_assets", sa.JSON(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("allowed_sides", sa.JSON(), nullable=False),
        sa.Column("expected_regimes", sa.JSON(), nullable=False),
        sa.Column("falsification_conditions", sa.JSON(), nullable=False),
        sa.Column("required_data", sa.JSON(), nullable=False),
        sa.Column("benchmark_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "research_hypothesis_annotations",
        sa.Column("annotation_id", sa.Text(), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column("annotation", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "research_dataset_snapshots",
        sa.Column("dataset_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("source_registry_version", sa.Text(), nullable=False),
        sa.Column("product_registry_version", sa.Text(), nullable=False),
        sa.Column("calendar_version", sa.Text(), nullable=False),
        sa.Column("pit", sa.Boolean(), nullable=False),
        sa.Column("missing_data_policy", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("pit = TRUE", name="ck_research_dataset_pit_true"),
        sa.CheckConstraint(
            "start_at_utc <= end_at_utc",
            name="ck_research_dataset_window_order",
        ),
        sa.CheckConstraint(
            "end_at_utc <= as_of_utc",
            name="ck_research_dataset_no_future_data",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "research_experiments",
        sa.Column("experiment_id", sa.Text(), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column(
            "parent_experiment_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_experiments.experiment_id"),
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at_utc", sa.DateTime(timezone=True)),
        sa.Column("research_state", sa.Text(), nullable=False),
        sa.Column("parameter_spec", sa.JSON(), nullable=False),
        sa.Column("parameter_space_hash", sa.Text(), nullable=False),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.research_dataset_snapshots.dataset_snapshot_id"
            ),
            nullable=False,
        ),
        sa.Column("code_commit_sha", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column(
            "supersedes_experiment_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_experiments.experiment_id"),
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "backtest_runs",
        sa.Column("backtest_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.research_experiments.experiment_id"),
            nullable=False,
        ),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.research_dataset_snapshots.dataset_snapshot_id"
            ),
            nullable=False,
        ),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("code_commit_sha", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("cost_model_version", sa.Text(), nullable=False),
        sa.Column("execution_model_version", sa.Text(), nullable=False),
        sa.Column("random_seed", sa.BigInteger()),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("integrity_flags", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "fold_results",
        sa.Column("fold_result_id", sa.Text(), primary_key=True),
        sa.Column(
            "backtest_run_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.backtest_runs.backtest_run_id"),
            nullable=False,
        ),
        sa.Column("fold_index", sa.Integer(), nullable=False),
        sa.Column("train_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("expectancy_r", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("stop_rate", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("cost_drag", sa.Float(), nullable=False),
        sa.Column("benchmark_result", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "backtest_run_id",
            "fold_index",
            name="uq_fold_result_run_index",
        ),
        sa.CheckConstraint("n >= 0", name="ck_fold_result_n_nonnegative"),
        sa.CheckConstraint(
            "train_start_utc <= train_end_utc "
            "AND train_end_utc < test_start_utc "
            "AND test_start_utc <= test_end_utc",
            name="ck_fold_result_chronological",
        ),
        schema=SCHEMA,
    )
    for table in (
        "research_hypotheses",
        "research_hypothesis_annotations",
        "research_dataset_snapshots",
        "research_experiments",
        "backtest_runs",
        "fold_results",
    ):
        _immutable(table)


def downgrade() -> None:
    for table in (
        "fold_results",
        "backtest_runs",
        "research_experiments",
        "research_dataset_snapshots",
        "research_hypothesis_annotations",
        "research_hypotheses",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}"
        )
        op.drop_table(table, schema=SCHEMA)
