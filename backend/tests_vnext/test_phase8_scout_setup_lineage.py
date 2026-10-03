from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.family_a import FamilyAContext, evaluate_family_a_structure
from aether_vnext.family_c import FamilyCContext, evaluate_family_c_range
from aether_vnext.playbook_engine import resolve_closed_bar_runtime
from aether_vnext.playbooks import playbook
from aether_vnext.regime import RegimeTags
from aether_vnext.scout import build_watch_setup, canonical_route_id
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 20, 45, tzinfo=UTC)
BAR_CLOSE = datetime(2026, 9, 26, 20, 30, tzinfo=UTC)


def _regime_tags(*, as_of_utc: datetime = BAR_CLOSE) -> RegimeTags:
    return RegimeTags(
        trend_range="trend",
        realized_volatility_band="mid",
        session="ny",
        spread_cost_band="normal",
        event_risk_state="normal",
        data_quality_state="healthy",
        as_of_utc=as_of_utc,
    )


def _engine_store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        policy = store.tables["policy_snapshots"]
        conn.execute(
            policy.insert().values(
                configuration_hash="cfg-8a",
                policy_version="AETHER-POLICY-8A",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase8",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(
            conn,
            MarketObservation(
                observation_id="obs-eurusd-1",
                asset_id="eurusd",
                venue="tastyfx",
                bid=1.1000,
                ask=1.1002,
                last=1.1001,
                mark=1.1001,
                source="test",
                exchange_ts=T0,
                received_ts=T0,
                age_ms=0,
                spread_abs=0.0002,
                spread_bps=1.818,
                session_state=SessionState.ACTIVE,
                quality_state=QualityState.HEALTHY,
                fallback_reason=None,
                calendar_state=CalendarState.NORMAL,
                data_version="test-v1",
            ),
        )
        store.record_market_observation(
            conn,
            MarketObservation(
                observation_id="obs-eth-1",
                asset_id="eth",
                venue="kraken",
                bid=4000.0,
                ask=4001.0,
                last=4000.5,
                mark=4000.5,
                source="test",
                exchange_ts=T0,
                received_ts=T0,
                age_ms=0,
                spread_abs=1.0,
                spread_bps=2.5,
                session_state=SessionState.ACTIVE,
                quality_state=QualityState.HEALTHY,
                fallback_reason=None,
                calendar_state=CalendarState.ALWAYS_OPEN,
                data_version="test-v1",
            ),
        )
    return engine, store


def _fx_watch_candidate():
    eval_a = evaluate_family_a_structure(
        playbook("pb_fx_intraday_v1_2"),
        asset_id="eurusd",
        side="long",
        context=FamilyAContext(
            close=1.1010,
            volatility_percentile=50.0,
            reference_high=1.1000,
            slope_ema20_current=1.1005,
            slope_ema20_previous=1.1000,
        ),
    )
    decision = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(eval_a,),
    )
    assert len(decision.watch_candidates) == 1
    return decision.watch_candidates[0]


def _fx_setup(*, setup_id: str, firm_event_id: str):
    return build_watch_setup(
        _fx_watch_candidate(),
        setup_id=setup_id,
        firm_event_id=firm_event_id,
        policy_version="AETHER-POLICY-8A",
        configuration_hash="cfg-8a",
        market_observation_id="obs-eurusd-1",
        trigger_bar_close_exchange_ts=BAR_CLOSE,
        created_at_utc=T0,
        invalidation=1.1000,
        quality=0.8,
        regime_tags=_regime_tags(),
        intel_pack={"closed_bar": True},
    )


def test_scout_builder_stamps_canonical_route_playbook_cluster_and_exit_contract() -> None:
    setup = _fx_setup(setup_id="setup-1", firm_event_id="firm-1")
    assert setup.lineage.route_id == "eurusd:intraday:long"
    assert setup.lineage.playbook_id == "pb_fx_intraday_v1_2"
    assert setup.lineage.playbook_version == "1.2"
    assert setup.lineage.risk_cluster_id == "fx"
    assert setup.lineage.asset_risk_hitches == {}
    assert setup.exit_contract_complete is True
    assert setup.exit_contract_gap is None
    assert setup.trigger_bar_close_exchange_ts == BAR_CLOSE
    assert setup.regime_tags["trend_range"] == "trend"
    assert setup.regime_tags["realized_volatility_band"] == "mid"
    assert setup.regime_tags["session"] == "ny"
    assert setup.regime_tags["spread_cost_band"] == "normal"
    assert setup.regime_tags["event_risk_state"] == "normal"
    assert setup.regime_tags["data_quality_state"] == "healthy"


def test_watch_setup_round_trips_through_durable_book() -> None:
    engine, store = _engine_store()
    setup = _fx_setup(setup_id="setup-1", firm_event_id="firm-1")
    with engine.begin() as conn:
        store.record_watch_setup(conn, setup)
    with engine.begin() as conn:
        loaded = store.load_setup(conn, setup_id="setup-1")
        assert loaded is not None
        assert loaded == setup

        lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id
                == "firm-1"
            )
        ).mappings().one()
        assert lineage["playbook_id"] == "pb_fx_intraday_v1_2"
        assert lineage["playbook_version"] == "1.2"
        assert lineage["risk_cluster_id"] == "fx"
        assert lineage["asset_risk_hitches"] == {}


def test_same_playbook_asset_horizon_side_cannot_watch_twice_on_same_closed_bar() -> None:
    engine, store = _engine_store()
    one = _fx_setup(setup_id="setup-1", firm_event_id="firm-1")
    two = _fx_setup(setup_id="setup-2", firm_event_id="firm-2")
    with engine.begin() as conn:
        store.record_watch_setup(conn, one)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_watch_setup(conn, two)


def test_store_rejects_noncanonical_cluster_before_insert() -> None:
    engine, store = _engine_store()
    setup = _fx_setup(setup_id="setup-1", firm_event_id="firm-1")
    bad_lineage = setup.lineage.__class__(
        **{
            **{
                field: getattr(setup.lineage, field)
                for field in setup.lineage.__dataclass_fields__
            },
            "risk_cluster_id": "us_beta",
        }
    )
    bad_setup = setup.__class__(
        **{
            **{
                field: getattr(setup, field)
                for field in setup.__dataclass_fields__
            },
            "lineage": bad_lineage,
        }
    )
    with pytest.raises(ValueError, match="risk_cluster_id"):
        with engine.begin() as conn:
            store.record_watch_setup(conn, bad_setup)


def test_family_c_may_watch_but_persists_incomplete_exit_contract() -> None:
    engine, store = _engine_store()
    eval_c = evaluate_family_c_range(
        playbook("pb_fx_range_v1_3"),
        asset_id="eurusd",
        side="long",
        context=FamilyCContext(
            close=1.0990,
            volatility_percentile=20.0,
            prior_range_high=1.1010,
            prior_range_low=1.1000,
            slope_ema20_current=1.1000,
            slope_ema20_previous=1.1000,
        ),
    )
    decision = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_c=(eval_c,),
    )
    candidate = decision.watch_candidates[0]
    setup = build_watch_setup(
        candidate,
        setup_id="setup-c",
        firm_event_id="firm-c",
        policy_version="AETHER-POLICY-8A",
        configuration_hash="cfg-8a",
        market_observation_id="obs-eurusd-1",
        trigger_bar_close_exchange_ts=BAR_CLOSE,
        created_at_utc=T0,
        invalidation=None,
        quality=None,
        regime_tags=_regime_tags(),
    )
    assert setup.exit_contract_complete is False
    assert "stop anchor" in str(setup.exit_contract_gap)
    with engine.begin() as conn:
        store.record_watch_setup(conn, setup)
        loaded = store.load_setup(conn, setup_id="setup-c")
    assert loaded is not None
    assert loaded.exit_contract_complete is False


def test_eth_rider_watch_stamps_50pct_btc_asset_risk_hitch() -> None:
    engine, store = _engine_store()
    rider = evaluate_family_a_structure(
        playbook("pb_eth_rider_v1_2"),
        asset_id="eth",
        side="long",
        context=FamilyAContext(
            close=4001.0,
            volatility_percentile=50.0,
            reference_high=4000.0,
            trend_ema20=4100.0,
            trend_ema50=3900.0,
            btc_parent_watch_or_open_long=True,
            btc_parent_market_regime_eligible=True,
        ),
    )
    decision = resolve_closed_bar_runtime(
        asset_id="eth",
        horizon="daily_swing",
        family_a=(rider,),
    )
    candidate = decision.watch_candidates[0]
    setup = build_watch_setup(
        candidate,
        setup_id="setup-eth",
        firm_event_id="firm-eth",
        policy_version="AETHER-POLICY-8A",
        configuration_hash="cfg-8a",
        market_observation_id="obs-eth-1",
        trigger_bar_close_exchange_ts=BAR_CLOSE,
        created_at_utc=T0,
        invalidation=None,
        quality=None,
        regime_tags=_regime_tags(),
    )
    assert setup.lineage.risk_cluster_id == "crypto"
    assert setup.lineage.asset_risk_hitches == {"btc": 0.50}
    assert setup.exit_contract_complete is False
    with engine.begin() as conn:
        store.record_watch_setup(conn, setup)
        loaded = store.load_setup(conn, setup_id="setup-eth")
    assert loaded is not None
    assert loaded.lineage.asset_risk_hitches == {"btc": 0.50}


def test_canonical_route_formula_is_exact() -> None:
    assert canonical_route_id(
        asset_id="nvda",
        horizon="intraday",
        side="short",
    ) == "nvda:intraday:short"


def test_scout_rejects_future_regime_information() -> None:
    with pytest.raises(ValueError, match="future information"):
        build_watch_setup(
            _fx_watch_candidate(),
            setup_id="setup-future-regime",
            firm_event_id="firm-future-regime",
            policy_version="AETHER-POLICY-8A",
            configuration_hash="cfg-8a",
            market_observation_id="obs-eurusd-1",
            trigger_bar_close_exchange_ts=BAR_CLOSE,
            created_at_utc=T0,
            invalidation=1.1000,
            quality=0.8,
            regime_tags=_regime_tags(
                as_of_utc=BAR_CLOSE.replace(minute=31)
            ),
        )
