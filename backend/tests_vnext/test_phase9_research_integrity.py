from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.freeze import ResearchState
from aether_vnext.research import (
    BacktestRun,
    FoldResult,
    HypothesisCard,
    ResearchDatasetSnapshot,
    ResearchExperiment,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 15, tzinfo=UTC)


def _card(hypothesis_id: str = "hyp-1") -> HypothesisCard:
    return HypothesisCard(
        hypothesis_id=hypothesis_id,
        created_at_utc=T0,
        hypothesis_text="Breakout continuation earns after costs.",
        economic_rationale="Persistent order flow after structural break.",
        mechanism_class="breakout_continuation",
        eligible_assets=("eurusd", "usdjpy"),
        horizon="intraday",
        allowed_sides=("long", "short"),
        expected_regimes=("trend",),
        falsification_conditions=("net_expectancy_le_0",),
        required_data=("15m_bars",),
        benchmark_ids=("always_flat",),
        status=ResearchState.FROZEN,
        annotations=("initial freeze",),
    )


def _snapshot() -> ResearchDatasetSnapshot:
    return ResearchDatasetSnapshot(
        dataset_snapshot_id="ds-1",
        created_at_utc=T0,
        as_of_utc=T0,
        start_at_utc=T0 - timedelta(days=90),
        end_at_utc=T0 - timedelta(days=1),
        asset_ids=("eurusd", "usdjpy"),
        data_version="bars-v1",
        source_registry_version="sources-v1",
        product_registry_version="products-v1",
        calendar_version="cal-v1",
        pit=True,
        missing_data_policy="fail_closed",
        content_hash="dataset-hash",
    )


def _experiment(experiment_id: str = "exp-1", state=ResearchState.FROZEN) -> ResearchExperiment:
    return ResearchExperiment(
        experiment_id=experiment_id,
        hypothesis_id="hyp-1",
        parent_experiment_id=None,
        created_at_utc=T0,
        frozen_at_utc=T0,
        research_state=state,
        parameter_spec={"lookback": 20},
        parameter_space_hash=f"space-{experiment_id}",
        dataset_snapshot_id="ds-1",
        code_commit_sha="abc123",
        configuration_hash="cfg-research-1",
        owner="Research",
        supersedes_experiment_id=None,
    )


def _run(run_id: str = "run-1", experiment_id: str = "exp-1") -> BacktestRun:
    return BacktestRun(
        backtest_run_id=run_id,
        experiment_id=experiment_id,
        run_type="held_out",
        dataset_snapshot_id="ds-1",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        code_commit_sha="abc123",
        configuration_hash="cfg-research-1",
        cost_model_version="cost-v1",
        execution_model_version="fill-v1",
        random_seed=7,
        started_at_utc=T0,
        finished_at_utc=T0 + timedelta(minutes=2),
        status="FAILED_EVIDENCE",
        integrity_flags=("negative_expectancy",),
        metrics_json={"net_expectancy": -1.0},
    )


def _fold() -> FoldResult:
    return FoldResult(
        fold_result_id="fold-1",
        backtest_run_id="run-1",
        fold_index=1,
        train_start_utc=T0 - timedelta(days=60),
        train_end_utc=T0 - timedelta(days=31),
        test_start_utc=T0 - timedelta(days=30),
        test_end_utc=T0 - timedelta(days=1),
        n=10,
        net_pnl=-10.0,
        expectancy_r=-0.1,
        profit_factor=0.8,
        stop_rate=0.6,
        max_drawdown=12.0,
        cost_drag=4.0,
        benchmark_result={"benchmark_id": "always_flat"},
        passed=False,
        failure_reasons=("negative_expectancy",),
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hypothesis_id", " hyp-1 "),
        ("hypothesis_text", 1),
        ("economic_rationale", " rationale "),
        ("mechanism_class", ""),
        ("horizon", " intraday "),
    ),
)
def test_hypothesis_card_requires_canonical_scalar_identity(
    field: str,
    value: object,
) -> None:
    base = _card()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        HypothesisCard(**kwargs)


def test_research_ledger_retains_failed_candidate_and_reproducibility_lineage() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(conn, _experiment())
        store.record_backtest_run(conn, _run())
        store.record_fold_result(conn, _fold())

        experiment = conn.execute(
            sa.select(store.tables["research_experiments"])
        ).mappings().one()
        run = conn.execute(
            sa.select(store.tables["backtest_runs"])
        ).mappings().one()
        fold = conn.execute(
            sa.select(store.tables["fold_results"])
        ).mappings().one()
        annotations = conn.execute(
            sa.select(store.tables["research_hypothesis_annotations"])
        ).mappings().all()

    assert experiment["parameter_space_hash"] == "space-exp-1"
    assert experiment["configuration_hash"] == "cfg-research-1"
    assert run["dataset_snapshot_id"] == "ds-1"
    assert run["code_commit_sha"] == "abc123"
    assert run["playbook_version"] == "1.2"
    assert run["random_seed"] == 7
    assert run["status"] == "FAILED_EVIDENCE"
    assert fold["passed"] is False
    assert fold["failure_reasons"] == ["negative_expectancy"]
    assert len(annotations) == 1


def test_parameter_variants_require_distinct_experiment_ids() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(conn, _experiment())
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_research_experiment(
                conn,
                ResearchExperiment(
                    **{
                        field: (
                            {"lookback": 40}
                            if field == "parameter_spec"
                            else getattr(_experiment(), field)
                        )
                        for field in _experiment().__dataclass_fields__
                    }
                ),
            )


def test_dataset_snapshot_rejects_future_data_and_non_pit() -> None:
    base = _snapshot()
    with pytest.raises(ValueError, match="PIT"):
        ResearchDatasetSnapshot(
            **{
                field: (
                    False if field == "pit" else getattr(base, field)
                )
                for field in base.__dataclass_fields__
            }
        )
    with pytest.raises(ValueError, match="after as_of"):
        ResearchDatasetSnapshot(
            **{
                field: (
                    T0 + timedelta(days=1)
                    if field == "end_at_utc"
                    else getattr(base, field)
                )
                for field in base.__dataclass_fields__
            }
        )


def test_fold_result_rejects_random_shuffle_geometry() -> None:
    with pytest.raises(ValueError, match="chronological"):
        FoldResult(
            fold_result_id="bad-fold",
            backtest_run_id="run-1",
            fold_index=1,
            train_start_utc=T0 - timedelta(days=10),
            train_end_utc=T0 - timedelta(days=1),
            test_start_utc=T0 - timedelta(days=5),
            test_end_utc=T0,
            n=1,
            net_pnl=0.0,
            expectancy_r=0.0,
            profit_factor=0.0,
            stop_rate=0.0,
            max_drawdown=0.0,
            cost_drag=0.0,
            benchmark_result={},
            passed=False,
            failure_reasons=("bad_fold",),
        )


def test_failed_and_retired_experiments_remain_queryable() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(
            conn,
            _experiment("exp-failed", ResearchState.RETIRED),
        )
        rows = conn.execute(
            sa.select(store.tables["research_experiments"])
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["experiment_id"] == "exp-failed"
    assert rows[0]["research_state"] == "RETIRED"
