from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.freeze import CONFIGURATION_HASH, ResearchState
from aether_vnext.held_out_evidence_window import (
    assemble_held_out_evidence_window,
)
from aether_vnext.held_out_fold_assembly import (
    ReplayTradeOutcome,
    assemble_held_out_fold,
)
from aether_vnext.held_out_manifest_assembly import (
    assemble_held_out_research_manifest,
)
from aether_vnext.held_out_replay_results import ReplayResultStatus
from aether_vnext.held_out_research_runner import (
    HeldOutFoldPlan,
    HeldOutReplayWorkItem,
)
from aether_vnext.playbooks import playbook
from aether_vnext.research import (
    BacktestRun,
    HypothesisCard,
    ResearchDatasetSnapshot,
    ResearchExperiment,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
ROUTE_ID = "nvda:intraday:long"
PLAYBOOK_ID = "pb_eq_intraday_v1_2"
POLICY_VERSION = "policy-v1"
CODE_SHA = "a" * 40


def _canonical_chain():
    spec = playbook(PLAYBOOK_ID)
    hypothesis = HypothesisCard(
        hypothesis_id="hypothesis-nvda-intraday",
        created_at_utc=T0,
        hypothesis_text="NVDA intraday continuation hypothesis",
        economic_rationale="Canonical replay manifest assembly fixture",
        mechanism_class=spec.mechanism_class,
        eligible_assets=("nvda",),
        horizon=spec.horizon,
        allowed_sides=("long",),
        expected_regimes=("eligible_mid_volatility",),
        falsification_conditions=("negative_net_edge",),
        required_data=("pit_bars",),
        benchmark_ids=("always_flat",),
        status=ResearchState.FROZEN,
    )
    dataset = ResearchDatasetSnapshot(
        dataset_snapshot_id="dataset-nvda-1",
        created_at_utc=T0,
        as_of_utc=T0 + timedelta(days=120),
        start_at_utc=T0,
        end_at_utc=T0 + timedelta(days=119),
        asset_ids=("nvda",),
        data_version="dataset-v1",
        source_registry_version="sources-v1",
        product_registry_version="products-v1",
        calendar_version="calendar-v1",
        pit=True,
        missing_data_policy="fail_closed",
        content_hash="d" * 64,
    )
    experiment = ResearchExperiment(
        experiment_id="experiment-nvda-1",
        hypothesis_id=hypothesis.hypothesis_id,
        parent_experiment_id=None,
        created_at_utc=T0,
        frozen_at_utc=T0 + timedelta(seconds=1),
        research_state=ResearchState.FROZEN,
        parameter_spec={"fixture": True},
        parameter_space_hash="e" * 64,
        dataset_snapshot_id=dataset.dataset_snapshot_id,
        code_commit_sha=CODE_SHA,
        configuration_hash=CONFIGURATION_HASH,
        owner="aether-test",
        supersedes_experiment_id=None,
    )
    run = BacktestRun(
        backtest_run_id="run-nvda-1",
        experiment_id=experiment.experiment_id,
        run_type="held_out",
        dataset_snapshot_id=dataset.dataset_snapshot_id,
        playbook_id=PLAYBOOK_ID,
        playbook_version=spec.version,
        code_commit_sha=CODE_SHA,
        configuration_hash=CONFIGURATION_HASH,
        cost_model_version="cost-v1",
        execution_model_version="execution-v1",
        random_seed=7,
        started_at_utc=T0 + timedelta(days=59),
        finished_at_utc=T0 + timedelta(days=90),
        status="COMPLETE",
        integrity_flags=(),
        metrics_json={},
    )
    return hypothesis, dataset, experiment, run


def _fold_assembly():
    spec = playbook(PLAYBOOK_ID)
    fold = HeldOutFoldPlan(
        fold_index=0,
        train_start_utc=T0,
        train_end_utc=T0 + timedelta(days=59),
        test_start_utc=T0 + timedelta(days=60),
        test_end_utc=T0 + timedelta(days=89),
    )
    work = HeldOutReplayWorkItem(
        work_item_id="work-nvda-0",
        route_id=ROUTE_ID,
        playbook_id=PLAYBOOK_ID,
        playbook_version=spec.version,
        mechanism_class=spec.mechanism_class,
        dataset_snapshot_id="dataset-nvda-1",
        dataset_content_hash="d" * 64,
        fold_index=0,
        test_start_utc=fold.test_start_utc,
        test_end_utc=fold.test_end_utc,
        code_commit_sha=CODE_SHA,
        configuration_hash=CONFIGURATION_HASH,
    )
    opened = fold.test_start_utc + timedelta(days=1)
    trade = ReplayTradeOutcome(
        trade_id="trade-nvda-1",
        opened_at_utc=opened,
        closed_at_utc=opened + timedelta(hours=2),
        gross_pnl_usd=12.0,
        base_cost_usd=2.0,
        net_r=0.5,
        stopped=False,
        capture_efficiency=0.4,
    )
    return assemble_held_out_fold(
        work,
        fold,
        backtest_run_id="run-nvda-1",
        trades=(trade,),
        replay_status=ReplayResultStatus.COMPLETE,
        benchmark_result={"benchmark_id": "always_flat"},
        passed=True,
    )


def test_manifest_assembly_packages_existing_canonical_objects() -> None:
    hypothesis, dataset, experiment, run = _canonical_chain()
    fold = _fold_assembly()
    window = assemble_held_out_evidence_window(
        (fold,),
        policy_version=POLICY_VERSION,
        configuration_hash=CONFIGURATION_HASH,
        created_at_utc=T0 + timedelta(days=90),
    )

    out = assemble_held_out_research_manifest(
        policy_version=POLICY_VERSION,
        configuration_hash=CONFIGURATION_HASH,
        source_ref="reviewed-held-out-replay:v1",
        hypotheses=(hypothesis,),
        datasets=(dataset,),
        experiments=(experiment,),
        runs=(run,),
        fold_assemblies=(fold,),
        window_assemblies=(window,),
    )

    assert out.manifest.configuration_hash == CONFIGURATION_HASH
    assert out.manifest.policy_version == POLICY_VERSION
    assert out.manifest.folds == (fold.fold_result,)
    assert out.manifest.windows[0].window == window.window
    assert out.manifest.windows[0].fold_result_ids == window.fold_result_ids
    assert out.validation_report["supplied_route_count"] == 1
    assert out.validation_report["window_count"] == 1
    assert out.validation_report["missing_route_count"] > 0


def test_manifest_assembly_refuses_noncanonical_configuration() -> None:
    hypothesis, dataset, experiment, run = _canonical_chain()
    fold = _fold_assembly()
    window = assemble_held_out_evidence_window(
        (fold,),
        policy_version=POLICY_VERSION,
        configuration_hash=CONFIGURATION_HASH,
        created_at_utc=T0 + timedelta(days=90),
    )

    with pytest.raises(ValueError, match="canonical configuration_hash"):
        assemble_held_out_research_manifest(
            policy_version=POLICY_VERSION,
            configuration_hash="not-canonical",
            source_ref="reviewed-held-out-replay:v1",
            hypotheses=(hypothesis,),
            datasets=(dataset,),
            experiments=(experiment,),
            runs=(run,),
            fold_assemblies=(fold,),
            window_assemblies=(window,),
        )


def test_manifest_assembly_refuses_window_policy_drift() -> None:
    hypothesis, dataset, experiment, run = _canonical_chain()
    fold = _fold_assembly()
    window = assemble_held_out_evidence_window(
        (fold,),
        policy_version="other-policy",
        configuration_hash=CONFIGURATION_HASH,
        created_at_utc=T0 + timedelta(days=90),
    )

    with pytest.raises(ValueError, match="window policy_version mismatch"):
        assemble_held_out_research_manifest(
            policy_version=POLICY_VERSION,
            configuration_hash=CONFIGURATION_HASH,
            source_ref="reviewed-held-out-replay:v1",
            hypotheses=(hypothesis,),
            datasets=(dataset,),
            experiments=(experiment,),
            runs=(run,),
            fold_assemblies=(fold,),
            window_assemblies=(window,),
        )


def test_manifest_assembly_requires_nonempty_immutable_inputs() -> None:
    hypothesis, dataset, experiment, run = _canonical_chain()
    fold = _fold_assembly()
    window = assemble_held_out_evidence_window(
        (fold,),
        policy_version=POLICY_VERSION,
        configuration_hash=CONFIGURATION_HASH,
        created_at_utc=T0 + timedelta(days=90),
    )

    with pytest.raises(ValueError, match="fold_assemblies"):
        assemble_held_out_research_manifest(
            policy_version=POLICY_VERSION,
            configuration_hash=CONFIGURATION_HASH,
            source_ref="reviewed-held-out-replay:v1",
            hypotheses=(hypothesis,),
            datasets=(dataset,),
            experiments=(experiment,),
            runs=(run,),
            fold_assemblies=(),
            window_assemblies=(window,),
        )
