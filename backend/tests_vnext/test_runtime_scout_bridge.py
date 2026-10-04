from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
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
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 7, 15, tzinfo=UTC)
CLOSE = T0 + timedelta(minutes=15)


def _cycle():
    bar = Bar(
        asset_id="eurusd",
        interval=timedelta(minutes=15),
        bucket_open_utc=T0,
        bucket_close_utc=CLOSE,
        open=1.1000,
        high=1.1020,
        low=1.0990,
        close=1.1015,
        volume=100.0,
        first_exchange_ts=T0 + timedelta(seconds=1),
        last_exchange_ts=CLOSE - timedelta(microseconds=1),
        print_count=20,
        source_id="test",
    )
    evaluation = FamilyAEvaluation(
        playbook_id="pb_fx_intraday_v1_2",
        asset_id="eurusd",
        side="long",
        definition_enabled=True,
        regime_eligible=True,
        structure_rule=True,
        dependency_ok=True,
    )
    return evaluate_closed_bar_cycle(
        ClosedBarCycleInput(
            asset_id="eurusd",
            horizon="intraday",
            trigger_bar=bar,
            family_a=(evaluation,),
        )
    )


def _regime() -> RegimeTags:
    return RegimeTags(
        trend_range="trend",
        realized_volatility_band="eligible_40_85",
        session="fx_active",
        spread_cost_band="normal",
        event_risk_state="clear",
        data_quality_state="healthy",
        as_of_utc=CLOSE,
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
                effective_at_utc=T0,
                changed_by="test",
                change_reason="runtime scout bridge",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(
            conn,
            MarketObservation(
                observation_id="obs-runtime-watch",
                asset_id="eurusd",
                venue="test",
                bid=1.1014,
                ask=1.1016,
                last=1.1015,
                mark=1.1015,
                source="test",
                exchange_ts=CLOSE,
                received_ts=CLOSE,
                age_ms=0,
                spread_abs=0.0002,
                spread_bps=(0.0002 / 1.1015) * 10_000.0,
                session_state=SessionState.ACTIVE,
                quality_state=QualityState.HEALTHY,
                fallback_reason=None,
                calendar_state=CalendarState.NORMAL,
                data_version="test",
            ),
        )
    return engine, store


def test_cycle_watch_candidate_persists_exact_scout_setup() -> None:
    engine, store = _book()
    cycle = _cycle()
    with engine.begin() as conn:
        setups = persist_cycle_watch_setups(
            conn,
            store,
            cycle=cycle,
            materializations=(
                WatchMaterialization(
                    playbook_id="pb_fx_intraday_v1_2",
                    side="long",
                    setup_id="setup-runtime-watch",
                    firm_event_id="firm-runtime-watch",
                    invalidation=1.0990,
                    quality=0.9,
                    intel_pack={"source": "runtime-cycle"},
                ),
            ),
            policy_version="runtime-policy-v1",
            configuration_hash=CONFIGURATION_HASH,
            market_observation_id="obs-runtime-watch",
            created_at_utc=CLOSE,
            regime_tags=_regime(),
        )
        loaded = store.load_setup(
            conn,
            setup_id="setup-runtime-watch",
        )

    assert len(setups) == 1
    assert loaded is not None
    assert loaded.state.value == "WATCH"
    assert loaded.lineage.playbook_id == "pb_fx_intraday_v1_2"
    assert loaded.lineage.route_id == "eurusd:intraday:long"
    assert loaded.trigger_bar_close_exchange_ts == CLOSE
    assert loaded.lineage.market_observation_id == "obs-runtime-watch"
    assert loaded.intel_pack == {"source": "runtime-cycle"}


def test_materialization_mismatch_fails_before_any_setup_write() -> None:
    engine, store = _book()
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="materialization mismatch"):
            persist_cycle_watch_setups(
                conn,
                store,
                cycle=_cycle(),
                materializations=(),
                policy_version="runtime-policy-v1",
                configuration_hash=CONFIGURATION_HASH,
                market_observation_id="obs-runtime-watch",
                created_at_utc=CLOSE,
                regime_tags=_regime(),
            )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["setups"])
        ).scalar_one()

    assert count == 0


def test_extra_watch_materialization_is_rejected() -> None:
    engine, store = _book()
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="materialization mismatch"):
            persist_cycle_watch_setups(
                conn,
                store,
                cycle=_cycle(),
                materializations=(
                    WatchMaterialization(
                        playbook_id="pb_fx_intraday_v1_2",
                        side="long",
                        setup_id="setup-runtime-watch",
                        firm_event_id="firm-runtime-watch",
                        invalidation=1.0990,
                        quality=0.9,
                    ),
                    WatchMaterialization(
                        playbook_id="pb_fx_intraday_v1_2",
                        side="short",
                        setup_id="extra",
                        firm_event_id="extra-firm",
                        invalidation=1.1030,
                        quality=0.5,
                    ),
                ),
                policy_version="runtime-policy-v1",
                configuration_hash=CONFIGURATION_HASH,
                market_observation_id="obs-runtime-watch",
                created_at_utc=CLOSE,
                regime_tags=_regime(),
            )
