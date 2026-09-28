"""Test support for provenance-bound HELD_OUT EvidenceWindow rows."""
from __future__ import annotations

from datetime import timedelta

from aether_vnext.freeze import ResearchState
from aether_vnext.research import (
    BacktestRun,
    FoldResult,
    HypothesisCard,
    ResearchDatasetSnapshot,
    ResearchExperiment,
)


def record_provenanced_held_out(conn, store, window) -> str:
    """Create a minimal valid research chain and persist one HELD_OUT window."""
    token = window.evidence_window_id
    asset_id, horizon, side = window.route_id.split(":")
    hypothesis_id = f"hyp:{token}"
    dataset_id = f"dataset:{token}"
    experiment_id = f"experiment:{token}"
    run_id = f"run:{token}"
    fold_id = f"fold:{token}"

    store.record_research_hypothesis(
        conn,
        HypothesisCard(
            hypothesis_id=hypothesis_id,
            created_at_utc=window.created_at_utc,
            hypothesis_text="test held-out provenance hypothesis",
            economic_rationale="test-only deterministic provenance fixture",
            mechanism_class="test_fixture",
            eligible_assets=(asset_id,),
            horizon=horizon,
            allowed_sides=(side,),
            expected_regimes=("test",),
            falsification_conditions=("negative_net_edge",),
            required_data=("pit_bars",),
            benchmark_ids=("test-baseline",),
            status=ResearchState.FROZEN,
        ),
    )
    store.record_research_dataset_snapshot(
        conn,
        ResearchDatasetSnapshot(
            dataset_snapshot_id=dataset_id,
            created_at_utc=window.created_at_utc,
            as_of_utc=max(window.created_at_utc, window.last_timestamp_utc),
            start_at_utc=window.first_timestamp_utc - timedelta(days=60),
            end_at_utc=window.last_timestamp_utc,
            asset_ids=(asset_id,),
            data_version="test-bars-v1",
            source_registry_version="test-sources-v1",
            product_registry_version="test-products-v1",
            calendar_version="test-calendar-v1",
            pit=True,
            missing_data_policy="fail_closed",
            content_hash=f"dataset-hash:{token}",
        ),
    )
    store.record_research_experiment(
        conn,
        ResearchExperiment(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis_id,
            parent_experiment_id=None,
            created_at_utc=window.created_at_utc,
            frozen_at_utc=window.created_at_utc,
            research_state=ResearchState.FROZEN,
            parameter_spec={"fixture": token},
            parameter_space_hash=f"parameter-space:{token}",
            dataset_snapshot_id=dataset_id,
            code_commit_sha="test-commit",
            configuration_hash=window.configuration_hash,
            owner="test",
            supersedes_experiment_id=None,
        ),
    )
    store.record_backtest_run(
        conn,
        BacktestRun(
            backtest_run_id=run_id,
            experiment_id=experiment_id,
            run_type="held_out",
            dataset_snapshot_id=dataset_id,
            playbook_id=window.playbook_id,
            playbook_version=window.playbook_version,
            code_commit_sha="test-commit",
            configuration_hash=window.configuration_hash,
            cost_model_version="test-cost-v1",
            execution_model_version="test-execution-v1",
            random_seed=7,
            started_at_utc=window.created_at_utc,
            finished_at_utc=max(
                window.created_at_utc,
                window.last_timestamp_utc,
            ) + timedelta(minutes=1),
            status="COMPLETE",
            integrity_flags=(),
            metrics_json={"n": window.n},
        ),
    )
    store.record_fold_result(
        conn,
        FoldResult(
            fold_result_id=fold_id,
            backtest_run_id=run_id,
            fold_index=1,
            train_start_utc=window.first_timestamp_utc - timedelta(days=60),
            train_end_utc=window.first_timestamp_utc - timedelta(seconds=1),
            test_start_utc=window.first_timestamp_utc,
            test_end_utc=window.last_timestamp_utc,
            n=window.n,
            net_pnl=0.0,
            expectancy_r=0.0,
            profit_factor=1.0,
            stop_rate=0.0,
            max_drawdown=0.0,
            cost_drag=0.0,
            benchmark_result={"fixture": True},
            passed=True,
            failure_reasons=(),
        ),
    )
    return store.record_held_out_evidence_window(
        conn,
        window,
        backtest_run_id=run_id,
        fold_result_ids=(fold_id,),
    )
