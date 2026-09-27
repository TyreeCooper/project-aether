from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.domain import ReviewCard
from aether_vnext.evidence import CostSensitivity, ProfitabilityEvidence
from aether_vnext.freeze import EvidenceState
from aether_vnext.review import ReviewGateInput
from aether_vnext.store import VNextStore


UTC = timezone.utc
NOW = datetime(2026, 9, 26, 22, 0, tzinfo=UTC)


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    verdict: str = "EVIDENCE_ACCUMULATING",
    n_trades: int = 12,
) -> ProfitabilityEvidence:
    return ProfitabilityEvidence(
        evidence_id=evidence_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="policy-9a",
        configuration_hash="cfg-9a",
        data_version="bars-v1",
        fill_model_version="paper-fill-v1",
        fee_schedule_version="fees-v1",
        in_sample_window=None,
        oos_windows=(
            {"fold": 1, "n": 6},
            {"fold": 2, "n": 6},
        ),
        n_trades=n_trades,
        net_expectancy_usd=3.5,
        profit_factor=1.1,
        win_rate=0.50,
        avg_win_usd=10.0,
        avg_loss_usd=-8.0,
        stop_rate=0.40,
        max_drawdown_usd=25.0,
        max_drawdown_pct=0.01,
        median_duration_s=1800.0,
        capture_efficiency=0.45,
        cost_sensitivity=CostSensitivity(
            base={"expectancy_usd": 3.5},
            plus25={"expectancy_usd": 2.0},
            plus50={"expectancy_usd": 0.5},
        ),
        regime_matrix={"trend": {"n": 7}, "range": {"n": 5}},
        benchmark_result={"not_worse_than_baseline": True},
        capacity_result={
            "status": "unvalidated",
            "trusted_keep_ready": False,
        },
        portfolio_contribution={"status": "unvalidated"},
        model_risks=("capacity_pending",),
        verdict=verdict,
        reviewer="Review",
        as_of_utc=NOW,
    )


def _gate_input(
    *,
    evidence_id: str = "evidence-1",
    n_closed: int = 12,
    net_expectancy: float = 3.5,
    stop_rate: float = 0.40,
    profit_factor: float = 1.1,
) -> ReviewGateInput:
    return ReviewGateInput(
        evidence_id=evidence_id,
        n_closed=n_closed,
        fold_expectancy_after_plus25_cost=(1.0, 1.0),
        expectancy_ci_lower=None,
        net_expectancy_after_costs=net_expectancy,
        profit_factor=profit_factor,
        stop_rate=stop_rate,
        baseline_not_worse=True,
        folds_chronological=True,
        integrity_clear=True,
        current_route_risk_fraction=0.0075,
        radar_eligible_routes=12,
        prior_evidence_state=EvidenceState.CANDIDATE,
        last10_stop_grind_confirmed=False,
    )


def _card(
    *,
    review_card_id: str = "review-1",
    evidence_id: str = "evidence-1",
    state: str = "EVIDENCE_ACCUMULATING",
) -> ReviewCard:
    return ReviewCard(
        review_card_id=review_card_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        as_of_utc=NOW,
        evidence_state=state,
        evidence_id=evidence_id,
        decision_reason="evidence still accumulating",
        reviewer="Review",
        configuration_hash="cfg-9a",
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9a",
                policy_version="policy-9a",
                effective_at_utc=NOW,
                changed_by="test",
                change_reason="phase9 evidence",
                payload={},
                created_at_utc=NOW,
            )
        )
    return engine, store


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("review_card_id", " review-1 ", "review_card_id must be canonical text"),
        ("route_id", 1, "route_id must be canonical text"),
        ("playbook_id", "", "playbook_id must be canonical text"),
        ("playbook_version", " 1.2 ", "playbook_version must be canonical text"),
        ("evidence_state", 1, "evidence_state must be canonical text"),
        ("evidence_id", " evidence-1 ", "evidence_id must be canonical text when present"),
        ("decision_reason", "", "decision_reason must be canonical text"),
        ("reviewer", " Review ", "reviewer must be canonical text"),
        ("configuration_hash", 1, "configuration_hash must be canonical text"),
    ),
)
def test_review_card_requires_canonical_identity(
    field: str,
    value: object,
    message: str,
) -> None:
    base = _card()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        ReviewCard(**kwargs)


def test_review_card_requires_timezone_aware_as_of() -> None:
    base = _card()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs["as_of_utc"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="as_of_utc must be timezone-aware"):
        ReviewCard(**kwargs)


def test_profitability_evidence_round_trips_and_review_points_to_it() -> None:
    engine, store = _store()
    evidence = _evidence()
    card = _card()
    with engine.begin() as conn:
        returned = store.record_profitability_review(
            conn,
            evidence=evidence,
            review_card=card,
            gate_input=_gate_input(),
        )
        assert returned == card

    with engine.begin() as conn:
        loaded_evidence = store.load_profitability_evidence(
            conn, evidence_id=evidence.evidence_id
        )
        loaded_card = store.load_review_card(
            conn, review_card_id=card.review_card_id
        )
        route = conn.execute(
            sa.select(store.tables["route_review_state"]).where(
                store.tables["route_review_state"].c.route_id
                == evidence.route_id
            )
        ).mappings().one()

    assert loaded_evidence == evidence
    assert loaded_card == card
    assert route["evidence_state"] == "EVIDENCE_ACCUMULATING"
    assert route["review_card_id"] == card.review_card_id
    assert route["operational_state"] == "ENABLED"
    assert route["row_version"] == 1


def test_profitability_evidence_reload_rejects_noncanonical_identity() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
            gate_input=_gate_input(),
        )
        table = store.tables["profitability_evidence"]
        conn.execute(
            table.update()
            .where(table.c.evidence_id == "evidence-1")
            .values(route_id=" eurusd:intraday:long ")
        )

        with pytest.raises(ValueError, match="route_id must be canonical text"):
            store.load_profitability_evidence(
                conn,
                evidence_id="evidence-1",
            )


def test_review_card_reload_rejects_noncanonical_identity() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
            gate_input=_gate_input(),
        )
        table = store.tables["review_cards"]
        conn.execute(
            table.update()
            .where(table.c.review_card_id == "review-1")
            .values(route_id=" eurusd:intraday:long ")
        )

        with pytest.raises(ValueError, match="route_id must be canonical text"):
            store.load_review_card(
                conn,
                review_card_id="review-1",
            )


def test_second_review_updates_projection_but_preserves_prior_evidence_and_card() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
            gate_input=_gate_input(),
        )
    second_evidence = _evidence(
        evidence_id="evidence-2",
        verdict="EVIDENCE_ACCUMULATING",
        n_trades=20,
    )
    second_card = _card(
        review_card_id="review-2",
        evidence_id="evidence-2",
        state="EVIDENCE_ACCUMULATING",
    )
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=second_evidence,
            review_card=second_card,
            gate_input=_gate_input(
                evidence_id="evidence-2",
                n_closed=20,
            ),
        )

    with engine.begin() as conn:
        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["profitability_evidence"]
            )
        ).scalar_one()
        card_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["review_cards"]
            )
        ).scalar_one()
        route = conn.execute(
            sa.select(store.tables["route_review_state"]).where(
                store.tables["route_review_state"].c.route_id
                == second_evidence.route_id
            )
        ).mappings().one()

    assert evidence_count == 2
    assert card_count == 2
    assert route["evidence_state"] == "EVIDENCE_ACCUMULATING"
    assert route["review_card_id"] == "review-2"
    assert route["row_version"] == 2


def test_duplicate_evidence_id_is_database_rejected() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
            gate_input=_gate_input(),
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_profitability_review(
                conn,
                evidence=_evidence(),
                review_card=_card(
                    review_card_id="review-duplicate",
                ),
                gate_input=_gate_input(),
            )


def test_review_and_evidence_identity_mismatches_fail_before_write() -> None:
    engine, store = _store()
    bad_card = _card(state="CUT_SIZE")
    with pytest.raises(ValueError, match="verdict"):
        with engine.begin() as conn:
            store.record_profitability_review(
                conn,
                evidence=_evidence(),
                review_card=bad_card,
                gate_input=_gate_input(),
            )
    with engine.begin() as conn:
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["profitability_evidence"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["review_cards"]
            )
        ).scalar_one() == 0


def test_review_persistence_does_not_mutate_broker_money_state() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        assert store.provision_seed_ledgers_once(conn) is True
        before = tuple(
            sorted(
                (
                    row["broker_account_id"],
                    row["cash_available_usd"],
                    row["cash_reserved_usd"],
                    row["margin_used_usd"],
                    row["margin_available_usd"],
                )
                for row in store.ledger_rows(conn)
            )
        )
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
            gate_input=_gate_input(),
        )
        after = tuple(
            sorted(
                (
                    row["broker_account_id"],
                    row["cash_available_usd"],
                    row["cash_reserved_usd"],
                    row["margin_used_usd"],
                    row["margin_available_usd"],
                )
                for row in store.ledger_rows(conn)
            )
        )
    assert after == before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("evidence_id", " evidence-1 "),
        ("route_id", 1),
        ("playbook_id", " pb_fx_intraday_v1_2 "),
        ("playbook_version", ""),
        ("policy_version", " policy-9a "),
        ("configuration_hash", 1),
        ("data_version", ""),
        ("fill_model_version", " paper-fill-v1 "),
        ("fee_schedule_version", 1),
        ("verdict", ""),
        ("reviewer", " Review "),
    ),
)
def test_profitability_evidence_requires_canonical_identity(
    field: str,
    value: object,
) -> None:
    base = _evidence()
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        ProfitabilityEvidence(**kwargs)


def test_evidence_validates_core_shape() -> None:
    with pytest.raises(ValueError, match="n_trades"):
        _evidence(n_trades=-1)

    base = _evidence()
    with pytest.raises(ValueError, match="win_rate"):
        ProfitabilityEvidence(
            **{
                field: (
                    1.1
                    if field == "win_rate"
                    else getattr(base, field)
                )
                for field in base.__dataclass_fields__
            }
        )
