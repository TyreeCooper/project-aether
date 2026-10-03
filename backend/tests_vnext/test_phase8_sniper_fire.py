from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import sqlalchemy as sa

from aether_vnext.bars import Bar
from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.family_a import FamilyAContext, evaluate_family_a_structure
from aether_vnext.playbook_engine import resolve_closed_bar_runtime
from aether_vnext.playbook_exits import build_exit_geometry
from aether_vnext.playbooks import playbook
from aether_vnext.regime import RegimeTags
from aether_vnext.scout import build_watch_setup
from aether_vnext.sniper import evaluate_sniper_fire, signal_key_for_setup
from aether_vnext.store import VNextStore


UTC = timezone.utc
BAR_CLOSE = datetime(2026, 9, 26, 20, 30, tzinfo=UTC)
NOW = datetime(2026, 9, 26, 20, 45, tzinfo=UTC)


def _regime_tags() -> RegimeTags:
    return RegimeTags(
        trend_range="trend",
        realized_volatility_band="mid",
        session="ny",
        spread_cost_band="normal",
        event_risk_state="normal",
        data_quality_state="healthy",
        as_of_utc=BAR_CLOSE,
    )


def _bar() -> Bar:
    return Bar(
        asset_id="eurusd",
        interval=timedelta(minutes=15),
        bucket_open_utc=BAR_CLOSE - timedelta(minutes=15),
        bucket_close_utc=BAR_CLOSE,
        open=1.1000,
        high=1.1012,
        low=1.0998,
        close=1.1010,
        volume=100.0,
        first_exchange_ts=BAR_CLOSE - timedelta(minutes=14),
        last_exchange_ts=BAR_CLOSE - timedelta(seconds=1),
        print_count=10,
        source_id="test",
    )


def _obs(*, quality: QualityState = QualityState.HEALTHY) -> MarketObservation:
    return MarketObservation(
        observation_id="obs-fire",
        asset_id="eurusd",
        venue="tastyfx",
        bid=1.1008,
        ask=1.1010,
        last=1.1009,
        mark=1.1009,
        source="test",
        exchange_ts=NOW,
        received_ts=NOW,
        age_ms=0,
        spread_abs=0.0002,
        spread_bps=1.817,
        session_state=SessionState.ACTIVE,
        quality_state=quality,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="test-v1",
    )


def _watch_setup():
    ev = evaluate_family_a_structure(
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
    candidate = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(ev,),
    ).watch_candidates[0]
    return build_watch_setup(
        candidate,
        setup_id="setup-fire",
        firm_event_id="firm-fire",
        policy_version="AETHER-POLICY-8B",
        configuration_hash="cfg-8b",
        market_observation_id="obs-watch",
        trigger_bar_close_exchange_ts=BAR_CLOSE,
        created_at_utc=NOW,
        invalidation=1.1000,
        quality=0.9,
        regime_tags=_regime_tags(),
    )


def _stop() -> float:
    geometry = build_exit_geometry(
        playbook("pb_fx_intraday_v1_2"),
        side="long",
        entry_price=1.1010,
        atr=0.0010,
        filled_at_utc=NOW,
        frozen_breakout_level=1.1000,
    )
    assert geometry.hard_stop_price is not None
    return geometry.hard_stop_price


def test_signal_key_formula_is_source_exact() -> None:
    setup = _watch_setup()
    raw = "|".join(
        (
            "setup-fire",
            "eurusd",
            "intraday",
            "long",
            BAR_CLOSE.isoformat(),
        )
    )
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert signal_key_for_setup(setup) == expected


def test_sniper_fires_only_on_exact_completed_trigger_bar() -> None:
    setup = _watch_setup()
    decision = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    assert decision.fire is True
    assert decision.reject_code is None

    future = _bar().__class__(
        **{
            **{
                field: getattr(_bar(), field)
                for field in _bar().__dataclass_fields__
            },
            "bucket_close_utc": NOW + timedelta(minutes=15),
        }
    )
    blocked = evaluate_sniper_fire(
        setup,
        completed_bar=future,
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    assert blocked.fire is False
    assert blocked.reject_code == "forming_bar"


def test_sniper_rejects_invalidation_grain_loss_stale_market_and_bad_stop() -> None:
    setup = _watch_setup()
    invalid = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=True,
    )
    assert invalid.reject_code == "invalidation_hit"

    no_break = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=False,
        invalidation_hit=False,
    )
    assert no_break.reject_code == "no_completed_breakout"

    stale = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(quality=QualityState.STALE),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    assert stale.reject_code == "market_stale"

    bad_stop = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=1.1015,
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    assert bad_stop.reject_code == "illegal_stop_side"


def test_incomplete_exit_contract_cannot_materialize_fire() -> None:
    setup = _watch_setup()
    incomplete = setup.__class__(
        **{
            **{
                field: getattr(setup, field)
                for field in setup.__dataclass_fields__
            },
            "exit_contract_complete": False,
            "exit_contract_gap": "source gap",
        }
    )
    try:
        evaluate_sniper_fire(
            incomplete,
            completed_bar=_bar(),
            current_observation=_obs(),
            hard_stop_price=_stop(),
            as_of_utc=NOW,
            grain_valid=True,
            invalidation_hit=False,
        )
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete ExitPlan contract was allowed to FIRE")


def _store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-8b",
                policy_version="AETHER-POLICY-8B",
                effective_at_utc=NOW,
                changed_by="test",
                change_reason="phase8b",
                payload={},
                created_at_utc=NOW,
            )
        )
        for obs in (
            MarketObservation(
                observation_id="obs-watch",
                asset_id="eurusd",
                venue="tastyfx",
                bid=1.1000,
                ask=1.1002,
                last=1.1001,
                mark=1.1001,
                source="test",
                exchange_ts=BAR_CLOSE,
                received_ts=BAR_CLOSE,
                age_ms=0,
                spread_abs=0.0002,
                spread_bps=1.818,
                session_state=SessionState.ACTIVE,
                quality_state=QualityState.HEALTHY,
                fallback_reason=None,
                calendar_state=CalendarState.NORMAL,
                data_version="test-v1",
            ),
            _obs(),
        ):
            store.record_market_observation(conn, obs)
        store.record_watch_setup(conn, _watch_setup())
    return engine, store


def test_fire_ticket_persists_and_advances_setup_and_lineage() -> None:
    engine, store = _store()
    setup = _watch_setup()
    decision = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    with engine.begin() as conn:
        result = store.record_sniper_ticket(
            conn,
            setup_id="setup-fire",
            ticket_id="ticket-fire",
            decision=decision,
            market_observation_id="obs-fire",
            created_at_utc=NOW,
        )
        assert result["state"] == "FIRE"
    with engine.begin() as conn:
        ticket = store.load_ticket(conn, ticket_id="ticket-fire")
        setup_row = conn.execute(
            sa.select(store.tables["setups"]).where(
                store.tables["setups"].c.setup_id == "setup-fire"
            )
        ).mappings().one()
        lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id
                == "firm-fire"
            )
        ).mappings().one()
    assert ticket is not None
    assert ticket.state.value == "FIRE"
    assert ticket.quantity is None
    assert ticket.modeled_round_trip_cost_pct is None
    assert ticket.lineage.playbook_id == "pb_fx_intraday_v1_2"
    assert setup_row["state"] == "FIRE"
    assert lineage["ticket_id"] == "ticket-fire"
    assert lineage["market_observation_id"] == "obs-fire"


def test_duplicate_signal_key_is_rejected_without_second_ticket() -> None:
    engine, store = _store()
    setup = _watch_setup()
    decision = evaluate_sniper_fire(
        setup,
        completed_bar=_bar(),
        current_observation=_obs(),
        hard_stop_price=_stop(),
        as_of_utc=NOW,
        grain_valid=True,
        invalidation_hit=False,
    )
    with engine.begin() as conn:
        store.record_sniper_ticket(
            conn,
            setup_id="setup-fire",
            ticket_id="ticket-fire",
            decision=decision,
            market_observation_id="obs-fire",
            created_at_utc=NOW,
        )
        # Simulate a stale duplicate attempt by returning Setup state to WATCH;
        # signal uniqueness must still block a second Ticket.
        conn.execute(
            store.tables["setups"].update()
            .where(store.tables["setups"].c.setup_id == "setup-fire")
            .values(state="WATCH")
        )
    with engine.begin() as conn:
        result = store.record_sniper_ticket(
            conn,
            setup_id="setup-fire",
            ticket_id="ticket-duplicate",
            decision=decision,
            market_observation_id="obs-fire",
            created_at_utc=NOW,
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["tickets"])
        ).scalar_one()
    assert result["reject_code"] == "signal_key_duplicate"
    assert result["ticket_created"] is False
    assert count == 1
