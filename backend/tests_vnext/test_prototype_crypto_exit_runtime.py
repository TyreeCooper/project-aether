from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from aether_vnext.domain import MarketObservation
from aether_vnext.prototype_crypto_entry_plan import build_prototype_crypto_entry_plan
from aether_vnext.prototype_crypto_entry_runtime import advance_prototype_crypto_entry
from aether_vnext.prototype_crypto_exit_runtime import advance_prototype_crypto_exit
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar
from tests_vnext.test_prototype_crypto_entry_runtime import T0, _bar, _feature, _fixture, _obs


def _open_trade():
    engine, store, first = _fixture()
    plan = build_prototype_crypto_entry_plan(
        feature=_feature(),
        current_observation=first,
        as_of_utc=T0 + timedelta(seconds=2),
    )
    with engine.begin() as conn:
        submitted = advance_prototype_crypto_entry(
            conn,
            store,
            plan=plan,
            completed_bar=_bar(),
            current_observation=first,
            current_observations={"btc": first},
            as_of_utc=T0 + timedelta(seconds=2),
        )
        assert submitted.stage == "SUBMITTED"

    second = _obs("obs-prototype-open-fill", T0 + timedelta(seconds=3))
    with engine.begin() as conn:
        store.record_market_observation(conn, second)
        opened = advance_prototype_crypto_entry(
            conn,
            store,
            plan=plan,
            completed_bar=_bar(),
            current_observation=second,
            current_observations={"btc": second},
            as_of_utc=T0 + timedelta(seconds=3),
        )
        assert opened.stage == "OPEN"
    return engine, store, plan, opened.trade_id


def _market_observation(
    base: MarketObservation,
    *,
    observation_id: str,
    at,
    bid: float = 101_480.0,
    ask: float = 101_500.0,
):
    return MarketObservation(
        observation_id=observation_id,
        asset_id=base.asset_id,
        venue=base.venue,
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2.0,
        mark=(bid + ask) / 2.0,
        source=base.source,
        exchange_ts=at,
        received_ts=at,
        age_ms=0,
        spread_abs=ask - bid,
        spread_bps=((ask - bid) / ((bid + ask) / 2.0)) * 10_000.0,
        session_state=base.session_state,
        quality_state=base.quality_state,
        fallback_reason=None,
        calendar_state=base.calendar_state,
        data_version="exit-test",
    )


def _closed_hour(*, close: float, closed_at):
    return PrototypeMarketBar(
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=closed_at - timedelta(hours=1),
        bucket_close_utc=closed_at,
        open=100_000.0,
        high=max(101_000.0, close),
        low=min(98_000.0, close),
        close=close,
        volume=25.0,
        trade_count=200,
        source_id=KRAKEN_DAILY_SOURCE_ID,
        source_ref="kraken:test:exit-hour",
        available_at_utc=closed_at,
    )


def test_structure_exit_submits_then_flattens_on_later_cycle() -> None:
    engine, store, plan, trade_id = _open_trade()
    at1 = T0 + timedelta(hours=1)
    base = _obs("base-unused", at1)
    obs1 = _market_observation(
        base,
        observation_id="obs-prototype-exit-1",
        at=at1,
    )
    structure_bar = _closed_hour(
        close=float(plan.geometry.structure_invalidation_level) - 1.0,
        closed_at=at1,
    )

    with engine.begin() as conn:
        store.record_market_observation(conn, obs1)
        first = advance_prototype_crypto_exit(
            conn,
            store,
            trade_id=str(trade_id),
            current_observation=obs1,
            latest_completed_hourly_bar=structure_bar,
            as_of_utc=at1,
        )
        assert first.stage == "CLOSE_SUBMITTED"
        assert first.exit_reason == "structure"

    at2 = at1 + timedelta(seconds=1)
    obs2 = _market_observation(
        base,
        observation_id="obs-prototype-exit-2",
        at=at2,
    )
    with engine.begin() as conn:
        store.record_market_observation(conn, obs2)
        second = advance_prototype_crypto_exit(
            conn,
            store,
            trade_id=str(trade_id),
            current_observation=obs2,
            latest_completed_hourly_bar=structure_bar,
            as_of_utc=at2,
        )
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        closed_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["closed_trades"]
            )
        ).scalar_one()

    assert second.stage == "FLAT"
    assert second.exit_reason == "structure"
    assert active_count == 0
    assert closed_count == 1


def test_no_exit_trigger_keeps_open_trade_without_close_intent() -> None:
    engine, store, plan, trade_id = _open_trade()
    at = T0 + timedelta(hours=1)
    base = _obs("base-unused-hold", at)
    obs = _market_observation(
        base,
        observation_id="obs-prototype-hold",
        at=at,
    )
    healthy_bar = _closed_hour(
        close=float(plan.geometry.structure_invalidation_level) + 500.0,
        closed_at=at,
    )
    with engine.begin() as conn:
        store.record_market_observation(conn, obs)
        result = advance_prototype_crypto_exit(
            conn,
            store,
            trade_id=str(trade_id),
            current_observation=obs,
            latest_completed_hourly_bar=healthy_bar,
            as_of_utc=at,
        )
        close_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            ).where(store.tables["order_intents"].c.intent_kind == "CLOSE")
        ).scalar_one()

    assert result.stage == "OPEN"
    assert result.reason == "hold"
    assert close_count == 0
