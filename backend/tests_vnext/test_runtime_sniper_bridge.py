from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.bars import Bar
from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.regime import RegimeTags
from aether_vnext.runtime_cycle import ClosedBarCycleInput, evaluate_closed_bar_cycle
from aether_vnext.runtime_scout_bridge import (
    WatchMaterialization,
    persist_cycle_watch_setups,
)
from aether_vnext.runtime_sniper_bridge import (
    evaluate_and_persist_sniper_ticket,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
OPEN = datetime(2026, 9, 27, 7, 30, tzinfo=UTC)
CLOSE = OPEN + timedelta(minutes=15)
NOW = CLOSE + timedelta(minutes=1)


def _bar() -> Bar:
    return Bar(
        asset_id="eurusd",
        interval=timedelta(minutes=15),
        bucket_open_utc=OPEN,
        bucket_close_utc=CLOSE,
        open=1.1000,
        high=1.1020,
        low=1.0990,
        close=1.1015,
        volume=100.0,
        first_exchange_ts=OPEN + timedelta(seconds=1),
        last_exchange_ts=CLOSE - timedelta(microseconds=1),
        print_count=20,
        source_id="test",
    )


def _observation(observation_id: str, *, bid: float, ask: float):
    return MarketObservation(
        observation_id=observation_id,
        asset_id="eurusd",
        venue="test",
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2.0,
        mark=(bid + ask) / 2.0,
        source="test",
        exchange_ts=NOW,
        received_ts=NOW,
        age_ms=0,
        spread_abs=ask - bid,
        spread_bps=((ask - bid) / ((bid + ask) / 2.0)) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="test",
    )


def _book() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="runtime-policy-v1",
                effective_at_utc=OPEN,
                changed_by="test",
                change_reason="runtime sniper bridge",
                payload={},
                created_at_utc=OPEN,
            )
        )
        watch_obs = _observation(
            "obs-watch",
            bid=1.1013,
            ask=1.1015,
        )
        current_obs = _observation(
            "obs-fire",
            bid=1.1014,
            ask=1.1016,
        )
        store.record_market_observation(conn, watch_obs)
        store.record_market_observation(conn, current_obs)

        evaluation = FamilyAEvaluation(
            playbook_id="pb_fx_intraday_v1_2",
            asset_id="eurusd",
            side="long",
            definition_enabled=True,
            regime_eligible=True,
            structure_rule=True,
            dependency_ok=True,
        )
        cycle = evaluate_closed_bar_cycle(
            ClosedBarCycleInput(
                asset_id="eurusd",
                horizon="intraday",
                trigger_bar=_bar(),
                family_a=(evaluation,),
            )
        )
        persist_cycle_watch_setups(
            conn,
            store,
            cycle=cycle,
            materializations=(
                WatchMaterialization(
                    playbook_id="pb_fx_intraday_v1_2",
                    side="long",
                    setup_id="setup-runtime-fire",
                    firm_event_id="firm-runtime-fire",
                    invalidation=1.1000,
                    quality=0.9,
                ),
            ),
            policy_version="runtime-policy-v1",
            configuration_hash=CONFIGURATION_HASH,
            market_observation_id="obs-watch",
            created_at_utc=CLOSE,
            regime_tags=RegimeTags(
                trend_range="trend",
                realized_volatility_band="eligible_40_85",
                session="fx_active",
                spread_cost_band="normal",
                event_risk_state="clear",
                data_quality_state="healthy",
                as_of_utc=CLOSE,
            ),
        )
    return engine, store


def test_runtime_bridge_advances_watch_setup_to_fire_ticket() -> None:
    engine, store = _book()
    current = _observation("obs-fire", bid=1.1014, ask=1.1016)
    with engine.begin() as conn:
        decision, result = evaluate_and_persist_sniper_ticket(
            conn,
            store,
            setup_id="setup-runtime-fire",
            ticket_id="ticket-runtime-fire",
            completed_bar=_bar(),
            current_observation=current,
            hard_stop_price=1.0990,
            as_of_utc=NOW,
            grain_valid=True,
            invalidation_hit=False,
            created_at_utc=NOW,
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-fire",
        )

    assert decision.fire is True
    assert decision.reject_code is None
    assert result["state"] == "FIRE"
    assert ticket is not None
    assert ticket.state.value == "FIRE"
    assert ticket.quantity is None
    assert ticket.lineage.setup_id == "setup-runtime-fire"
    assert ticket.lineage.market_observation_id == "obs-fire"


def test_runtime_bridge_persists_sniper_rejection_without_sizing() -> None:
    engine, store = _book()
    current = _observation("obs-fire", bid=1.1014, ask=1.1016)
    with engine.begin() as conn:
        decision, result = evaluate_and_persist_sniper_ticket(
            conn,
            store,
            setup_id="setup-runtime-fire",
            ticket_id="ticket-runtime-reject",
            completed_bar=_bar(),
            current_observation=current,
            hard_stop_price=1.0990,
            as_of_utc=NOW,
            grain_valid=False,
            invalidation_hit=False,
            created_at_utc=NOW,
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-reject",
        )

    assert decision.fire is False
    assert decision.reject_code == "no_completed_breakout"
    assert result["state"] == "REJECTED"
    assert ticket is not None
    assert ticket.state.value == "REJECTED"
    assert ticket.quantity is None
