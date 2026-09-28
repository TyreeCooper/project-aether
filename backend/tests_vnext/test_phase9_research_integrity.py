from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.freeze import EvidenceState, ResearchState
from aether_vnext.research import (
    ALPHA_FACTORY_RUN_TYPES,
    EVIDENCE_BEARING_RUN_TYPES,
    BacktestRun,
    FoldResult,
    HypothesisCard,
    PromotionRecord,
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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dataset_snapshot_id", "ds-other"),
        ("code_commit_sha", "different-sha"),
        ("configuration_hash", "cfg-other"),
    ),
)
def test_backtest_run_rejects_experiment_lineage_drift(
    field: str,
    value: str,
) -> None:
    engine, store = _store()
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(conn, _experiment())
        with pytest.raises(
            ValueError,
            match=f"lineage mismatch: .*{field}",
        ):
            store.record_backtest_run(conn, BacktestRun(**kwargs))


def test_backtest_run_requires_canonical_playbook_version() -> None:
    engine, store = _store()
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["playbook_version"] = "9.9"

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(conn, _experiment())
        with pytest.raises(
            ValueError,
            match="playbook_version does not match canonical playbook",
        ):
            store.record_backtest_run(conn, BacktestRun(**kwargs))


@pytest.mark.parametrize(
    "run_type",
    tuple(sorted(EVIDENCE_BEARING_RUN_TYPES)),
)
def test_evidence_run_requires_frozen_experiment(run_type: str) -> None:
    engine, store = _store()
    base = _run()
    run_kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    run_kwargs["run_type"] = run_type

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(
            conn,
            _experiment(state=ResearchState.SPEC),
        )
        with pytest.raises(
            ValueError,
            match="requires a FROZEN experiment",
        ):
            store.record_backtest_run(conn, BacktestRun(**run_kwargs))


def test_evidence_run_requires_freeze_before_run_start() -> None:
    engine, store = _store()
    experiment = _experiment()
    experiment_kwargs = {
        name: getattr(experiment, name)
        for name in experiment.__dataclass_fields__
    }
    experiment_kwargs["frozen_at_utc"] = T0 + timedelta(minutes=1)

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(
            conn,
            ResearchExperiment(**experiment_kwargs),
        )
        with pytest.raises(
            ValueError,
            match="frozen before evidence run starts",
        ):
            store.record_backtest_run(conn, _run())


@pytest.mark.parametrize("run_type", ("backtest", "parameter_sensitivity"))
def test_exploratory_run_does_not_require_frozen_experiment(
    run_type: str,
) -> None:
    engine, store = _store()
    base = _run()
    run_kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    run_kwargs["run_type"] = run_type

    experiment = _experiment(state=ResearchState.SPEC)
    experiment_kwargs = {
        name: getattr(experiment, name)
        for name in experiment.__dataclass_fields__
    }
    experiment_kwargs["frozen_at_utc"] = None

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(
            conn,
            ResearchExperiment(**experiment_kwargs),
        )
        store.record_backtest_run(conn, BacktestRun(**run_kwargs))

        row = conn.execute(
            sa.select(store.tables["backtest_runs"])
        ).mappings().one()

    assert row["run_type"] == run_type


def test_backtest_run_rejects_unknown_experiment_before_persistence() -> None:
    engine, store = _store()
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["experiment_id"] = "missing-exp"

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        with pytest.raises(KeyError, match="unknown research experiment"):
            store.record_backtest_run(conn, BacktestRun(**kwargs))


def test_fold_persistence_requires_parent_run_and_dataset_window() -> None:
    engine, store = _store()
    base = _fold()

    with engine.begin() as conn:
        with pytest.raises(KeyError, match="unknown backtest_run_id"):
            store.record_fold_result(conn, base)

    outside_kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    outside_kwargs["train_start_utc"] = T0 - timedelta(days=91)
    outside = FoldResult(**outside_kwargs)

    with engine.begin() as conn:
        store.record_research_hypothesis(conn, _card())
        store.record_research_dataset_snapshot(conn, _snapshot())
        store.record_research_experiment(conn, _experiment())
        store.record_backtest_run(conn, _run())
        with pytest.raises(
            ValueError,
            match="contained in backtest research dataset",
        ):
            store.record_fold_result(conn, outside)


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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("experiment_id", " exp-1 ", "experiment_id must be canonical text"),
        ("hypothesis_id", 1, "hypothesis_id must be canonical text"),
        ("parameter_space_hash", "", "parameter_space_hash must be canonical text"),
        ("dataset_snapshot_id", " ds-1 ", "dataset_snapshot_id must be canonical text"),
        ("code_commit_sha", 1, "code_commit_sha must be canonical text"),
        ("configuration_hash", " cfg-research-1 ", "configuration_hash must be canonical text"),
        ("owner", "", "owner must be canonical text"),
        (
            "parent_experiment_id",
            " parent ",
            "parent_experiment_id must be canonical text when present",
        ),
        (
            "supersedes_experiment_id",
            1,
            "supersedes_experiment_id must be canonical text when present",
        ),
    ),
)
def test_research_experiment_requires_canonical_identity(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _experiment()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        ResearchExperiment(**kwargs)


def test_frozen_research_experiment_requires_freeze_timestamp() -> None:
    base = _experiment()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["frozen_at_utc"] = None

    with pytest.raises(
        ValueError,
        match="FROZEN research requires frozen_at_utc",
    ):
        ResearchExperiment(**kwargs)


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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dataset_snapshot_id", " ds-1 "),
        ("data_version", 1),
        ("source_registry_version", ""),
        ("product_registry_version", " products-v1 "),
        ("calendar_version", 1),
        ("missing_data_policy", " fail_closed "),
        ("content_hash", ""),
    ),
)
def test_dataset_snapshot_requires_canonical_scalar_identity(
    field: str,
    value: object,
) -> None:
    base = _snapshot()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        ResearchDatasetSnapshot(**kwargs)


@pytest.mark.parametrize(
    ("asset_ids", "message"),
    (
        (["eurusd"], "asset_ids must be a nonempty immutable tuple"),
        ((" EURUSD ",), "asset_ids must contain canonical asset IDs"),
        (("EURUSD",), "asset_ids must contain canonical asset IDs"),
        ((1,), "asset_ids must contain canonical asset IDs"),
        (("eurusd", "eurusd"), "asset_ids cannot contain duplicates"),
    ),
)
def test_dataset_snapshot_requires_canonical_asset_ids(
    asset_ids: object,
    message: str,
) -> None:
    base = _snapshot()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["asset_ids"] = asset_ids
    with pytest.raises(ValueError, match=message):
        ResearchDatasetSnapshot(**kwargs)


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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("backtest_run_id", " run-1 "),
        ("experiment_id", 1),
        ("run_type", " held_out "),
        ("dataset_snapshot_id", ""),
        ("playbook_id", " pb_fx_intraday_v1_2 "),
        ("playbook_version", 1),
        ("code_commit_sha", ""),
        ("configuration_hash", " cfg-research-1 "),
        ("cost_model_version", 1),
        ("execution_model_version", ""),
        ("status", " FAILED_EVIDENCE "),
    ),
)
def test_backtest_run_requires_canonical_identity(
    field: str,
    value: object,
) -> None:
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        BacktestRun(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("fold_result_id", " fold-1 "),
        ("fold_result_id", 1),
        ("backtest_run_id", ""),
        ("backtest_run_id", " run-1 "),
    ),
)
def test_fold_result_requires_canonical_identity(
    field: str,
    value: object,
) -> None:
    base = _fold()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        FoldResult(**kwargs)


@pytest.mark.parametrize(
    "run_type",
    tuple(sorted(ALPHA_FACTORY_RUN_TYPES)),
)
def test_backtest_run_accepts_source_bound_alpha_factory_modes(
    run_type: str,
) -> None:
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["run_type"] = run_type
    assert BacktestRun(**kwargs).run_type == run_type


def test_backtest_run_rejects_undefined_research_mode() -> None:
    base = _run()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["run_type"] = "ad_hoc_optimized"
    with pytest.raises(ValueError, match="source-bound Alpha Factory modes"):
        BacktestRun(**kwargs)


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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("fold_index", -1, "fold_index must be a nonnegative integer"),
        ("n", -1, "n must be a nonnegative integer"),
        ("stop_rate", 1.1, "stop_rate must be in"),
        ("max_drawdown", -1.0, "max_drawdown cannot be negative"),
        ("cost_drag", -1.0, "cost_drag cannot be negative"),
        ("net_pnl", float("nan"), "net_pnl must be finite"),
        ("profit_factor", float("nan"), "profit_factor must be nonnegative"),
        ("passed", 1, "passed must be boolean"),
    ),
)
def test_fold_result_rejects_invalid_metric_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _fold()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        FoldResult(**kwargs)


def test_fold_result_requires_timezone_aware_windows() -> None:
    base = _fold()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["test_end_utc"] = base.test_end_utc.replace(tzinfo=None)
    with pytest.raises(ValueError, match="test_end_utc must be timezone-aware"):
        FoldResult(**kwargs)


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

def _promotion() -> PromotionRecord:
    return PromotionRecord(
        promotion_id="promotion-1",
        route_id="eurusd:intraday:long",
        playbook_version="1.2",
        from_evidence_state=EvidenceState.CANDIDATE,
        to_evidence_state=EvidenceState.KEEP_PROBATION,
        review_card_id="review-1",
        evidence_window_id="window-1",
        reviewer="Review",
        approver="Risk",
        decided_at_utc=T0,
        decision_reason="source-bound evidence gate passed",
        configuration_hash="cfg-research-1",
        n_reset=False,
        supersedes=None,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("promotion_id", " promotion-1 ", "promotion_id must be canonical text"),
        ("route_id", 1, "route_id must be canonical text"),
        ("playbook_version", "", "playbook_version must be canonical text"),
        ("review_card_id", " review-1 ", "review_card_id must be canonical text"),
        ("evidence_window_id", 1, "evidence_window_id must be canonical text"),
        ("reviewer", "", "reviewer must be canonical text"),
        ("approver", " Risk ", "approver must be canonical text"),
        ("decision_reason", 1, "decision_reason must be canonical text"),
        ("configuration_hash", "", "configuration_hash must be canonical text"),
        (
            "supersedes",
            " promotion-0 ",
            "supersedes must be canonical text when present",
        ),
    ),
)
def test_promotion_record_requires_canonical_identity(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _promotion()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        PromotionRecord(**kwargs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "from_evidence_state",
            EvidenceState.CANDIDATE.value,
            "from_evidence_state must be an EvidenceState",
        ),
        (
            "to_evidence_state",
            EvidenceState.KEEP_PROBATION.value,
            "to_evidence_state must be an EvidenceState",
        ),
        ("n_reset", 1, "n_reset must be boolean"),
    ),
)
def test_promotion_record_requires_typed_transition_state(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _promotion()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        PromotionRecord(**kwargs)


def _persist_promotion_dependencies(
    conn: sa.Connection,
    store: VNextStore,
) -> None:
    conn.execute(
        store.tables["policy_snapshots"].insert().values(
            configuration_hash="cfg-research-1",
            policy_version="research-policy-v1",
            effective_at_utc=T0,
            changed_by="test",
            change_reason="research promotion test",
            payload={},
            created_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["evidence_windows"].insert().values(
            evidence_window_id="window-1",
            route_id="eurusd:intraday:long",
            playbook_id="pb_fx_intraday_v1_2",
            playbook_version="1.2",
            policy_version="research-policy-v1",
            configuration_hash="cfg-research-1",
            sample_domain="held_out",
            first_timestamp_utc=T0 - timedelta(days=30),
            last_timestamp_utc=T0 - timedelta(days=1),
            n=1,
            immutable_trade_ids=["trade-1"],
            metrics_snapshot_hash="metrics-1",
            created_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["review_cards"].insert().values(
            review_card_id="review-1",
            firm_event_id=None,
            trade_id=None,
            route_id="eurusd:intraday:long",
            playbook_id="pb_fx_intraday_v1_2",
            playbook_version="1.2",
            as_of_utc=T0,
            evidence_state=EvidenceState.KEEP_PROBATION.value,
            evidence_id=None,
            decision_reason="source-bound evidence gate passed",
            reviewer="Review",
            configuration_hash="cfg-research-1",
        )
    )


def test_promotion_record_persists_append_only_review_lineage() -> None:
    engine, store = _store()
    promotion = _promotion()
    with engine.begin() as conn:
        _persist_promotion_dependencies(conn, store)
        store.record_research_promotion(conn, promotion)
        row = conn.execute(
            sa.select(store.tables["research_promotions"])
        ).mappings().one()

    assert row["promotion_id"] == "promotion-1"
    assert row["route_id"] == "eurusd:intraday:long"
    assert row["from_evidence_state"] == EvidenceState.CANDIDATE.value
    assert row["to_evidence_state"] == EvidenceState.KEEP_PROBATION.value
    assert row["review_card_id"] == "review-1"
    assert row["evidence_window_id"] == "window-1"
    assert row["n_reset"] is False

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_research_promotion(conn, promotion)


def test_promotion_record_rejects_review_lineage_drift() -> None:
    engine, store = _store()
    base = _promotion()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["route_id"] = "usdjpy:intraday:long"

    with engine.begin() as conn:
        _persist_promotion_dependencies(conn, store)
        with pytest.raises(
            ValueError,
            match="research promotion lineage mismatch",
        ):
            store.record_research_promotion(
                conn,
                PromotionRecord(**kwargs),
            )


def test_promotion_record_requires_timezone_aware_decision_time() -> None:
    base = _promotion()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["decided_at_utc"] = T0.replace(tzinfo=None)
    with pytest.raises(ValueError, match="decided_at_utc must be timezone-aware"):
        PromotionRecord(**kwargs)

