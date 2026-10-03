from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.decay import (
    DecayCohort,
    DecayStatus,
    assess_decay,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 0, tzinfo=UTC)


def _cohort(
    evidence_id: str,
    *,
    at_utc: datetime,
    expectancy: float = 10.0,
    capture: float = 0.50,
    execution_drag: float = 1.0,
    average_cost: float = 2.0,
    regime_mix: dict[str, float] | None = None,
    route_id: str = "eurusd:intraday:long",
) -> DecayCohort:
    return DecayCohort(
        evidence_id=evidence_id,
        route_id=route_id,
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        configuration_hash="cfg-9f",
        as_of_utc=at_utc,
        n=20,
        net_expectancy_usd=expectancy,
        capture_efficiency=capture,
        execution_drag_usd_per_trade=execution_drag,
        average_cost_usd_per_trade=average_cost,
        regime_mix=regime_mix or {"trend": 0.5, "range": 0.5},
    )


def test_directional_decay_deltas_do_not_invent_materiality_threshold() -> None:
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=6.0,
        capture=0.40,
        execution_drag=1.5,
        average_cost=2.5,
        regime_mix={"trend": 0.2, "range": 0.8},
    )
    out = assess_decay(
        reference,
        recent,
        materiality_decision=None,
        materiality_policy_version=None,
    )
    assert out.status is DecayStatus.MATERIALITY_UNBOUND
    assert out.request_review is True
    assert out.expectancy_delta_usd == pytest.approx(-4.0)
    assert out.capture_efficiency_delta == pytest.approx(-0.10)
    assert out.execution_drag_delta_usd_per_trade == pytest.approx(0.5)
    assert out.average_cost_delta_usd_per_trade == pytest.approx(0.5)
    assert set(out.deterioration_dimensions) == {
        "net_expectancy",
        "capture_efficiency",
        "execution_drag",
        "cost_drift",
        "regime_mix_change",
    }
    assert "material_deterioration_threshold_unbound" in out.unresolved_rules
    assert "rolling_reference_window_size_unbound" in out.unresolved_rules


def test_bound_materiality_decision_controls_decay_confirmation_only() -> None:
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=8.0,
    )
    confirmed = assess_decay(
        reference,
        recent,
        materiality_decision=True,
        materiality_policy_version="decay-policy-v1",
    )
    assert confirmed.status is DecayStatus.DECAY_CONFIRMED
    assert confirmed.request_review is True
    assert confirmed.unresolved_rules == ()

    not_material = assess_decay(
        reference,
        recent,
        materiality_decision=False,
        materiality_policy_version="decay-policy-v1",
    )
    assert not_material.status is DecayStatus.NO_MATERIAL_DECAY
    assert not_material.request_review is False

    with pytest.raises(ValueError, match="materiality_policy_version"):
        assess_decay(
            reference,
            recent,
            materiality_decision=True,
            materiality_policy_version=None,
        )


def test_no_directional_deterioration_does_not_queue_review() -> None:
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=11.0,
        capture=0.55,
        execution_drag=0.9,
        average_cost=1.8,
    )
    out = assess_decay(
        reference,
        recent,
        materiality_decision=None,
        materiality_policy_version=None,
    )
    assert out.status is DecayStatus.NO_DECAY_SIGNAL
    assert out.request_review is False


def test_decay_cohorts_cannot_cross_route_or_version_family() -> None:
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        route_id="usdjpy:intraday:long",
    )
    with pytest.raises(ValueError, match="cannot cross evidence family"):
        assess_decay(
            reference,
            recent,
            materiality_decision=None,
            materiality_policy_version=None,
        )


def _insert_evidence(conn, store: VNextStore, evidence_id: str, at_utc: datetime) -> None:
    conn.execute(
        store.tables["profitability_evidence"].insert().values(
            evidence_id=evidence_id,
            route_id="eurusd:intraday:long",
            playbook_id="pb_fx_intraday_v1_2",
            playbook_version="1.2",
            policy_version="policy-9f",
            configuration_hash="cfg-9f",
            data_version="bars-v1",
            fill_model_version="fill-v1",
            fee_schedule_version="fees-v1",
            in_sample_window=None,
            oos_windows=[],
            n_trades=20,
            net_expectancy_usd=5.0,
            profit_factor=1.1,
            win_rate=0.5,
            avg_win_usd=10.0,
            avg_loss_usd=-8.0,
            stop_rate=0.4,
            max_drawdown_usd=25.0,
            max_drawdown_pct=0.01,
            median_duration_s=1800.0,
            capture_efficiency=0.4,
            cost_sensitivity={},
            regime_matrix={},
            benchmark_result={},
            capacity_result={},
            portfolio_contribution={},
            model_risks=[],
            verdict="EVIDENCE_ACCUMULATING",
            reviewer="Review",
            as_of_utc=at_utc,
        )
    )


def _store_fixture() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9f",
                policy_version="policy-9f",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase9f",
                payload={},
                created_at_utc=T0,
            )
        )
        _insert_evidence(conn, store, "e-ref", T0)
        _insert_evidence(conn, store, "e-new", T0 + timedelta(days=7))
        conn.execute(
            store.tables["route_review_state"].insert().values(
                route_id="eurusd:intraday:long",
                evidence_state="KEEP_TRUSTED",
                operational_state="ENABLED",
                review_card_id=None,
                updated_at_utc=T0,
                row_version=1,
            )
        )
        store.provision_seed_ledgers_once(conn)
    return engine, store


def test_monitor_automatically_queues_review_without_mutating_route_or_money() -> None:
    engine, store = _store_fixture()
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=6.0,
        capture=0.4,
    )
    with engine.begin() as conn:
        before_route = dict(
            conn.execute(
                sa.select(store.tables["route_review_state"])
            ).mappings().one()
        )
        before_ledgers = tuple(
            sorted(
                (
                    row["broker_account_id"],
                    row["cash_available_usd"],
                    row["cash_reserved_usd"],
                    row["margin_used_usd"],
                )
                for row in store.ledger_rows(conn)
            )
        )
        result = store.assess_and_queue_decay(
            conn,
            decay_request_id="decay-1",
            reference=reference,
            recent=recent,
            materiality_decision=None,
            materiality_policy_version=None,
            created_at_utc=T0 + timedelta(days=7),
        )
        after_route = dict(
            conn.execute(
                sa.select(store.tables["route_review_state"])
            ).mappings().one()
        )
        after_ledgers = tuple(
            sorted(
                (
                    row["broker_account_id"],
                    row["cash_available_usd"],
                    row["cash_reserved_usd"],
                    row["margin_used_usd"],
                )
                for row in store.ledger_rows(conn)
            )
        )
        review_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["review_cards"]
            )
        ).scalar_one()

    assert result["queued"] is True
    assert result["status"] == "MATERIALITY_UNBOUND"
    assert result["route_state_mutated"] is False
    assert after_route == before_route
    assert after_ledgers == before_ledgers
    assert review_count == 0

    with engine.begin() as conn:
        row = store.load_decay_review_request(
            conn,
            decay_request_id="decay-1",
        )
    assert row is not None
    assert row["request_review"] is True
    assert row["deterioration_dimensions"] == [
        "net_expectancy",
        "capture_efficiency",
    ]


def test_non_material_or_healthy_monitor_result_does_not_create_queue_row() -> None:
    engine, store = _store_fixture()
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=8.0,
    )
    with engine.begin() as conn:
        result = store.assess_and_queue_decay(
            conn,
            decay_request_id="should-not-persist",
            reference=reference,
            recent=recent,
            materiality_decision=False,
            materiality_policy_version="decay-policy-v1",
            created_at_utc=T0 + timedelta(days=7),
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["decay_review_requests"]
            )
        ).scalar_one()
    assert result["queued"] is False
    assert count == 0


def test_decay_queue_identity_is_append_only_unique() -> None:
    engine, store = _store_fixture()
    reference = _cohort("e-ref", at_utc=T0)
    recent = _cohort(
        "e-new",
        at_utc=T0 + timedelta(days=7),
        expectancy=6.0,
    )
    with engine.begin() as conn:
        store.assess_and_queue_decay(
            conn,
            decay_request_id="decay-1",
            reference=reference,
            recent=recent,
            materiality_decision=True,
            materiality_policy_version="decay-policy-v1",
            created_at_utc=T0 + timedelta(days=7),
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.assess_and_queue_decay(
                conn,
                decay_request_id="decay-1",
                reference=reference,
                recent=recent,
                materiality_decision=True,
                materiality_policy_version="decay-policy-v1",
                created_at_utc=T0 + timedelta(days=7),
            )
