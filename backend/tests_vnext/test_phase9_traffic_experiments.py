from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.store import VNextStore
from aether_vnext.traffic_experiments import (
    ShadowComparison,
    TrafficChangeFamily,
    TrafficExperiment,
    TrafficObservation,
    TrafficPromotionEvidence,
    TrafficStage,
    assert_experiment_evidence_isolated,
    assess_traffic_promotion,
    summarize_traffic,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 30, tzinfo=UTC)


def _experiment() -> TrafficExperiment:
    return TrafficExperiment(
        experiment_id="traffic-1",
        change_family=TrafficChangeFamily.SCOUT,
        control_configuration_hash="cfg-control",
        treatment_configuration_hash="cfg-treatment",
        hypothesis="One Scout gate change improves OOS net expectancy.",
        owner="Research",
        created_at_utc=T0,
    )


def _window(
    window_id: str,
    config: str,
    trade_ids: tuple[str, ...],
) -> EvidenceWindow:
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version=("policy-control" if config == "cfg-control" else "policy-treatment"),
        configuration_hash=config,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=T0,
        last_timestamp_utc=T0 + timedelta(days=7),
        n=len(trade_ids),
        immutable_trade_ids=trade_ids,
        metrics_snapshot_hash=f"metrics-{window_id}",
        created_at_utc=T0 + timedelta(days=8),
    )


def test_material_experiment_requires_distinct_configuration_hashes() -> None:
    with pytest.raises(ValueError, match="must differ"):
        TrafficExperiment(
            experiment_id="bad",
            change_family=TrafficChangeFamily.CLERK,
            control_configuration_hash="same",
            treatment_configuration_hash="same",
            hypothesis="bad",
            owner="Research",
            created_at_utc=T0,
        )


def test_traffic_summary_is_configuration_isolated_and_wait_is_not_reject() -> None:
    rows = (
        TrafficObservation("o1", "cfg-treatment", TrafficStage.UNIVERSE, 10),
        TrafficObservation("o1", "cfg-treatment", TrafficStage.WATCH, 20),
        TrafficObservation(
            "o2", "cfg-treatment", TrafficStage.UNIVERSE, 5,
            wait_or_deferred=True,
        ),
        TrafficObservation(
            "o3", "cfg-treatment", TrafficStage.WATCH, 7,
            terminal_reject=True,
            first_killed_by="Scout",
            first_kill_reason="no_setup",
        ),
    )
    out = summarize_traffic(rows, configuration_hash="cfg-treatment")
    assert out["wait_deferred_count"] == 1
    assert out["terminal_reject_count"] == 1
    assert out["first_killer_distribution"] == {"Scout:no_setup": 1}
    assert out["target_trade_count"] is None

    with pytest.raises(ValueError, match="cannot mix"):
        summarize_traffic(
            rows + (
                TrafficObservation("o4", "cfg-control", TrafficStage.OPEN, 1),
            ),
            configuration_hash="cfg-treatment",
        )


def test_shadow_comparison_can_never_create_order() -> None:
    with pytest.raises(ValueError, match="cannot create an order"):
        ShadowComparison(
            shadow_comparison_id="shadow-1",
            experiment_id="traffic-1",
            opportunity_id="opp-1",
            current_configuration_hash="cfg-treatment",
            prior_configuration_hash="cfg-control",
            would_pass_under_prior_policy=True,
            evaluated_at_utc=T0,
            order_created=True,
        )


def test_control_and_treatment_evidence_never_mix_or_overlap() -> None:
    experiment = _experiment()
    assert_experiment_evidence_isolated(
        experiment,
        control_windows=(_window("cw", "cfg-control", ("c1", "c2")),),
        treatment_windows=(_window("tw", "cfg-treatment", ("t1", "t2")),),
    )
    with pytest.raises(ValueError, match="wrong configuration_hash"):
        assert_experiment_evidence_isolated(
            experiment,
            control_windows=(_window("bad", "cfg-treatment", ("x",)),),
            treatment_windows=(_window("tw", "cfg-treatment", ("t",)),),
        )
    with pytest.raises(ValueError, match="overlaps"):
        assert_experiment_evidence_isolated(
            experiment,
            control_windows=(_window("cw", "cfg-control", ("same",)),),
            treatment_windows=(_window("tw", "cfg-treatment", ("same",)),),
        )


def test_promotion_requires_better_oos_expectancy_and_explicit_safety_acceptance() -> None:
    good = assess_traffic_promotion(
        TrafficPromotionEvidence(
            control_oos_net_expectancy_usd=2.0,
            treatment_oos_net_expectancy_usd=3.0,
            drawdown_acceptable=True,
            cost_acceptable=True,
            cluster_acceptable=True,
            control_oos=True,
            treatment_oos=True,
        )
    )
    assert good.promotion_eligible is True

    unresolved = assess_traffic_promotion(
        TrafficPromotionEvidence(
            control_oos_net_expectancy_usd=2.0,
            treatment_oos_net_expectancy_usd=3.0,
            drawdown_acceptable=None,
            cost_acceptable=True,
            cluster_acceptable=True,
            control_oos=True,
            treatment_oos=True,
        )
    )
    assert unresolved.promotion_eligible is False
    assert "drawdown_acceptable_criterion_unbound" in unresolved.unresolved_rules

    worse = assess_traffic_promotion(
        TrafficPromotionEvidence(
            control_oos_net_expectancy_usd=3.0,
            treatment_oos_net_expectancy_usd=2.0,
            drawdown_acceptable=True,
            cost_acceptable=True,
            cluster_acceptable=True,
            control_oos=True,
            treatment_oos=True,
        )
    )
    assert worse.promotion_eligible is False
    assert "treatment_oos_expectancy_not_improved" in worse.blocking_reasons


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        for cfg, policy in (
            ("cfg-control", "policy-control"),
            ("cfg-treatment", "policy-treatment"),
        ):
            conn.execute(
                store.tables["policy_snapshots"].insert().values(
                    configuration_hash=cfg,
                    policy_version=policy,
                    effective_at_utc=T0,
                    changed_by="test",
                    change_reason="traffic experiment",
                    payload={},
                    created_at_utc=T0,
                )
            )
    return engine, store


def test_traffic_experiment_and_shadow_are_durable_without_order_authority() -> None:
    engine, store = _store()
    experiment = _experiment()
    shadow = ShadowComparison(
        shadow_comparison_id="shadow-1",
        experiment_id=experiment.experiment_id,
        opportunity_id="opp-1",
        current_configuration_hash="cfg-treatment",
        prior_configuration_hash="cfg-control",
        would_pass_under_prior_policy=True,
        evaluated_at_utc=T0,
    )
    with engine.begin() as conn:
        store.record_traffic_experiment(conn, experiment)
        store.record_traffic_shadow_comparison(conn, shadow)
        row = conn.execute(
            sa.select(store.tables["traffic_shadow_comparisons"])
        ).mappings().one()
        order_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one()

    assert row["would_pass_under_prior_policy"] is True
    assert row["order_created"] is False
    assert order_count == 0


def test_duplicate_experiment_identity_is_rejected() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_traffic_experiment(conn, _experiment())
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_traffic_experiment(conn, _experiment())
