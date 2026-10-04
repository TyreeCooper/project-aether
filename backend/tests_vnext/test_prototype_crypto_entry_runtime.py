from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.prototype_crypto_entry_plan import build_prototype_crypto_entry_plan
from aether_vnext.prototype_crypto_entry_runtime import advance_prototype_crypto_entry
from aether_vnext.prototype_crypto_features import PrototypeCryptoFeatureSnapshot
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.store import VNextStore
from aether_vnext.volatility_percentile import VolatilityPercentileSnapshot
from tests_vnext.runtime_registry_support import record_test_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)


def _obs(observation_id: str, at: datetime) -> MarketObservation:
    bid = 101_480.0
    ask = 101_500.0
    mark = (bid + ask) / 2.0
    return MarketObservation(
        observation_id=observation_id,
        asset_id="btc",
        venue="Kraken",
        bid=bid,
        ask=ask,
        last=mark,
        mark=mark,
        source="kraken_public",
        exchange_ts=at,
        received_ts=at,
        age_ms=0,
        spread_abs=ask - bid,
        spread_bps=((ask - bid) / mark) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="test",
    )


def _feature() -> PrototypeCryptoFeatureSnapshot:
    vol = VolatilityPercentileSnapshot(
        asset_id="btc",
        interval=timedelta(hours=1),
        trigger_close_utc=T0,
        window_start_utc=T0 - timedelta(days=90),
        window_end_exclusive_utc=T0,
        current_realized_vol14=0.01,
        reference_count=2160,
        less_count=1296,
        equal_count=0,
        percentile=60.0,
    )
    return PrototypeCryptoFeatureSnapshot(
        asset_id="btc",
        trigger_close_utc=T0,
        close=101_500.0,
        atr14=1_000.0,
        prior_20h_high=101_000.0,
        prior_20h_low=95_000.0,
        daily_ema20=100_000.0,
        daily_ema50=98_000.0,
        btc_daily_close=101_000.0,
        btc_daily_ema50=98_000.0,
        volatility=vol,
        family_a=FamilyAEvaluation(
            playbook_id="pb_crypto_swing_v1_2",
            asset_id="btc",
            side="long",
            definition_enabled=True,
            regime_eligible=True,
            structure_rule=True,
            dependency_ok=True,
        ),
    )


def _bar() -> PrototypeMarketBar:
    return PrototypeMarketBar(
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=T0 - timedelta(hours=1),
        bucket_close_utc=T0,
        open=100_900.0,
        high=101_600.0,
        low=100_800.0,
        close=101_500.0,
        volume=100.0,
        trade_count=500,
        source_id=KRAKEN_DAILY_SOURCE_ID,
        source_ref="kraken:test:completed-hour",
        available_at_utc=T0,
    )


def _fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    first = _obs("obs-prototype-entry-1", T0 + timedelta(seconds=2))
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="prototype-paper-policy-v1",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="prototype entry runtime",
                payload={},
                created_at_utc=T0,
            )
        )
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        store.record_market_observation(conn, first)
    return engine, store, first


def test_entry_state_machine_reaches_submitted_then_open_on_later_cycle() -> None:
    engine, store, first = _fixture()
    plan = build_prototype_crypto_entry_plan(
        feature=_feature(),
        current_observation=first,
        as_of_utc=T0 + timedelta(seconds=2),
    )

    with engine.begin() as conn:
        first_result = advance_prototype_crypto_entry(
            conn,
            store,
            plan=plan,
            completed_bar=_bar(),
            current_observation=first,
            current_observations={"btc": first},
            as_of_utc=T0 + timedelta(seconds=2),
        )
    assert first_result.stage == "SUBMITTED"

    second = _obs("obs-prototype-entry-2", T0 + timedelta(seconds=3))
    with engine.begin() as conn:
        store.record_market_observation(conn, second)
        second_result = advance_prototype_crypto_entry(
            conn,
            store,
            plan=plan,
            completed_bar=_bar(),
            current_observation=second,
            current_observations={"btc": second},
            as_of_utc=T0 + timedelta(seconds=3),
        )
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        trade_count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["open_trades"])
        ).scalar_one()

    assert second_result.stage == "OPEN"
    assert active_count == 1
    assert trade_count == 1


def test_entry_state_machine_no_structure_makes_no_book_mutation() -> None:
    engine, store, first = _fixture()
    feature = _feature()
    blocked = PrototypeCryptoFeatureSnapshot(
        asset_id=feature.asset_id,
        trigger_close_utc=feature.trigger_close_utc,
        close=feature.close,
        atr14=feature.atr14,
        prior_20h_high=feature.prior_20h_high,
        prior_20h_low=feature.prior_20h_low,
        daily_ema20=feature.daily_ema20,
        daily_ema50=feature.daily_ema50,
        btc_daily_close=feature.btc_daily_close,
        btc_daily_ema50=feature.btc_daily_ema50,
        volatility=feature.volatility,
        family_a=FamilyAEvaluation(
            playbook_id="pb_crypto_swing_v1_2",
            asset_id="btc",
            side="long",
            definition_enabled=True,
            regime_eligible=True,
            structure_rule=False,
            dependency_ok=True,
        ),
    )
    plan = build_prototype_crypto_entry_plan(
        feature=blocked,
        current_observation=first,
        as_of_utc=T0 + timedelta(seconds=2),
    )
    with engine.begin() as conn:
        result = advance_prototype_crypto_entry(
            conn,
            store,
            plan=plan,
            completed_bar=_bar(),
            current_observation=first,
            current_observations={"btc": first},
            as_of_utc=T0 + timedelta(seconds=2),
        )
        setup_count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["setups"])
        ).scalar_one()
        ticket_count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["tickets"])
        ).scalar_one()
    assert result.stage == "NO_SETUP"
    assert setup_count == 0
    assert ticket_count == 0
