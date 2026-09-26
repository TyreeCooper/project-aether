from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.domain import ReviewCard
from aether_vnext.evidence import CostSensitivity, ProfitabilityEvidence
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
        capacity_result={"status": "unvalidated"},
        portfolio_contribution={"status": "unvalidated"},
        model_risks=("capacity_pending",),
        verdict=verdict,
        reviewer="Review",
        as_of_utc=NOW,
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


def test_profitability_evidence_round_trips_and_review_points_to_it() -> None:
    engine, store = _store()
    evidence = _evidence()
    card = _card()
    with engine.begin() as conn:
        returned = store.record_profitability_review(
            conn,
            evidence=evidence,
            review_card=card,
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


def test_second_review_updates_projection_but_preserves_prior_evidence_and_card() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
        )
    second_evidence = _evidence(
        evidence_id="evidence-2",
        verdict="CUT_SIZE",
        n_trades=20,
    )
    second_card = _card(
        review_card_id="review-2",
        evidence_id="evidence-2",
        state="CUT_SIZE",
    )
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=second_evidence,
            review_card=second_card,
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
    assert route["evidence_state"] == "CUT_SIZE"
    assert route["review_card_id"] == "review-2"
    assert route["row_version"] == 2


def test_duplicate_evidence_id_is_database_rejected() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_profitability_review(
            conn,
            evidence=_evidence(),
            review_card=_card(),
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_profitability_review(
                conn,
                evidence=_evidence(),
                review_card=_card(
                    review_card_id="review-duplicate",
                ),
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
