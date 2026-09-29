from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.institutional_memory import (
    CounterfactualReplayRecord,
    ExperienceCoverage,
    FailureArchiveEntry,
    InstitutionalMemoryRecord,
    PnlAttributionComponent,
    PnlAttributionRecord,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _attribution(*, net_pnl_usd: float = 75.0) -> PnlAttributionRecord:
    return PnlAttributionRecord(
        attribution_id="attr-1",
        firm_id="aether",
        mechanism_id="trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        route_id="btc:1h:trend",
        asset_id="btc",
        horizon="1h",
        side="long",
        regime_id="trend-up",
        trade_id="trade-1",
        configuration_hash="cfg-1",
        net_pnl_usd=net_pnl_usd,
        components=(
            PnlAttributionComponent("alpha", 100.0),
            PnlAttributionComponent("fees", -10.0),
            PnlAttributionComponent(
                "slippage",
                net_pnl_usd - 90.0,
            ),
        ),
        attributed_at_utc=T0,
        source_record_ids=("trade-1", "fill-1"),
    )


def _memory(*, lesson: str = "retain verified continuation") -> InstitutionalMemoryRecord:
    return InstitutionalMemoryRecord(
        memory_id="memory-1",
        trade_id="trade-1",
        route_id="btc:1h:trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        configuration_hash="cfg-1",
        market_state_ref="market-1",
        information_state_ref="info-1",
        signal_ref="signal-1",
        decision_ref="decision-1",
        expected_outcome_ref="expected-1",
        actual_outcome_ref="actual-1",
        execution_quality_ref="execution-1",
        risk_state_ref="risk-1",
        success_failure_reason="clean continuation",
        lesson=lesson,
        future_relevance=("trend_up", "btc"),
        occurred_at_utc=T0,
        recorded_at_utc=T0 + timedelta(minutes=1),
        source_record_ids=("trade-1", "fill-1"),
    )


def _failure(*, reason: str = "slippage spike") -> FailureArchiveEntry:
    return FailureArchiveEntry(
        failure_id="failure-1",
        memory_id="memory-1",
        trade_id="trade-1",
        category="abnormal_slippage_spread_widening",
        reason=reason,
        recovery_lesson="retain spread shock as scar tissue",
        recorded_at_utc=T0 + timedelta(minutes=2),
        source_record_ids=("memory-1",),
    )


def _replay(*, result_ref: str = "cf-result-1") -> CounterfactualReplayRecord:
    return CounterfactualReplayRecord(
        replay_id="replay-1",
        original_memory_id="memory-1",
        variation_keys=("stop", "no_trade"),
        hypothetical_result_ref=result_ref,
        created_at_utc=T0 + timedelta(minutes=3),
    )


def _coverage(*, gaps: int = 2) -> ExperienceCoverage:
    return ExperienceCoverage(
        historical_years=4.0,
        unique_regimes_crises=9,
        event_categories=12,
        asset_event_combinations=30,
        execution_failure_scenarios=8,
        correlation_stress_scenarios=5,
        unique_market_state_clusters=21,
        forward_paper_days=100,
        forward_paper_trades=160,
        historical_forward_gaps=gaps,
    )


def test_pnl_attribution_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    record = _attribution()
    with engine.begin() as conn:
        store.record_pnl_attribution(conn, record)
        store.record_pnl_attribution(conn, record)

    with engine.begin() as conn:
        loaded = store.load_pnl_attribution(
            conn,
            attribution_id="attr-1",
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["pnl_attributions"]
            )
        ).scalar_one()
    assert loaded == record
    assert count == 1

    with pytest.raises(ValueError, match="conflicting immutable P&L attribution"):
        with engine.begin() as conn:
            store.record_pnl_attribution(conn, _attribution(net_pnl_usd=70.0))


def test_institutional_memory_round_trip_is_immutable() -> None:
    engine, store = _store()
    record = _memory()
    with engine.begin() as conn:
        store.record_institutional_memory(conn, record)
        store.record_institutional_memory(conn, record)

    with engine.begin() as conn:
        loaded = store.load_institutional_memory(
            conn,
            memory_id="memory-1",
        )
    assert loaded == record

    with pytest.raises(
        ValueError,
        match="conflicting immutable institutional memory",
    ):
        with engine.begin() as conn:
            store.record_institutional_memory(
                conn,
                _memory(lesson="changed lesson"),
            )


def test_failure_and_counterfactual_round_trip_remain_append_only() -> None:
    engine, store = _store()
    failure = _failure()
    replay = _replay()

    with engine.begin() as conn:
        store.record_failure_archive_entry(conn, failure)
        store.record_counterfactual_replay(conn, replay)

    with engine.begin() as conn:
        assert store.load_failure_archive_entry(
            conn,
            failure_id="failure-1",
        ) == failure
        loaded_replay = store.load_counterfactual_replay(
            conn,
            replay_id="replay-1",
        )

    assert loaded_replay == replay
    assert loaded_replay is not None
    assert loaded_replay.hypothetical is True
    assert loaded_replay.independent_evidence_credit is False

    with pytest.raises(
        ValueError,
        match="conflicting immutable failure archive entry",
    ):
        with engine.begin() as conn:
            store.record_failure_archive_entry(
                conn,
                _failure(reason="changed"),
            )

    with pytest.raises(
        ValueError,
        match="conflicting immutable counterfactual replay",
    ):
        with engine.begin() as conn:
            store.record_counterfactual_replay(
                conn,
                _replay(result_ref="changed"),
            )


def test_experience_coverage_round_trip_is_idempotent() -> None:
    engine, store = _store()
    coverage = _coverage()

    with engine.begin() as conn:
        store.record_experience_coverage(
            conn,
            coverage_id="coverage-1",
            as_of_utc=T0,
            coverage=coverage,
        )
        store.record_experience_coverage(
            conn,
            coverage_id="coverage-1",
            as_of_utc=T0,
            coverage=coverage,
        )

    with engine.begin() as conn:
        loaded = store.load_experience_coverage(
            conn,
            coverage_id="coverage-1",
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["experience_coverage_snapshots"]
            )
        ).scalar_one()

    assert loaded == coverage
    assert count == 1

    with pytest.raises(
        ValueError,
        match="conflicting immutable experience coverage snapshot",
    ):
        with engine.begin() as conn:
            store.record_experience_coverage(
                conn,
                coverage_id="coverage-1",
                as_of_utc=T0,
                coverage=_coverage(gaps=3),
            )
