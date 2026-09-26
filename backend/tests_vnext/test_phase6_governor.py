from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.restart import load_restart_snapshot
from aether_vnext.store import VNextStore, open_intent_idempotency_key


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 19, 40, tzinfo=UTC)


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-btc-governor",
        asset_id="btc",
        venue="Kraken",
        bid=99_990.0,
        ask=100_010.0,
        last=100_000.0,
        mark=100_000.0,
        source="kraken_public",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=10,
        spread_abs=20.0,
        spread_bps=2.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )


def _fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg",
                policy_version="policy-v1",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="test fixture",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, _obs())
        conn.execute(
            store.tables["exit_plans"].insert().values(
                exit_plan_id="exit-btc-governor",
                version="v1",
                hard_stop_price=95_000.0,
                structure_rule_id=None,
                time_stop_deadline_utc=None,
                trailing_policy={
                    "enabled": False,
                    "start_condition": None,
                    "ratchet_rule": None,
                    "never_loosen": True,
                },
                profit_take_policy={"enabled": False, "rule_id": None},
                session_close_policy="hold",
                stale_mark_policy="hold",
                governor_halt_behavior="hold",
                created_from_playbook_version="1.4",
                payload_hash="hash-exit-btc-governor",
                created_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-btc-governor",
                exit_plan_id="exit-btc-governor",
                setup_id="setup-btc-governor",
                firm_event_id=None,
                asset_id="btc",
                route_id="btc:daily_swing:long",
                state="READY",
                signal_key="signal-btc-governor",
                side="long",
                horizon="daily_swing",
                stop_price=95_000.0,
                quantity=0.001,
                modeled_round_trip_cost_pct=0.10,
                reject_code=None,
                policy_version="policy-v1",
                configuration_hash="cfg",
                market_observation_id="obs-btc-governor",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store


def _set(
    conn,
    store: VNextStore,
    *,
    scope_key: str,
    scope_type: str,
    scope_id: str | None,
    state: str = "HALT",
    event_id: str,
    expected_row_version: int | None = None,
    authenticated: bool = True,
):
    return store.set_governor_state(
        conn,
        scope_key=scope_key,
        scope_type=scope_type,
        scope_id=scope_id,
        state=state,
        governor_state_version="gov-v1",
        policy_version="policy-v1",
        configuration_hash="cfg",
        effective_at_utc=T0,
        reason=f"test {scope_type} {state.lower()}",
        actor="operator-test",
        authenticated=authenticated,
        expected_row_version=expected_row_version,
        event_id=event_id,
    )


def _reserve(conn, store: VNextStore):
    idem = open_intent_idempotency_key(
        ticket_id="ticket-btc-governor",
        side="long",
        quantity=0.001,
        asset_id="btc",
        horizon="daily_swing",
        signal_key="signal-btc-governor",
    )
    return store.reserve_risk_checked_open_intent(
        conn,
        order_intent_id="intent-btc-governor",
        ticket_id="ticket-btc-governor",
        firm_event_id=None,
        asset_id="btc",
        route_id="btc:daily_swing:long",
        broker_account_id="kraken_paper",
        broker="Kraken",
        venue="Kraken",
        symbol="XBTUSD",
        side="long",
        qty=0.001,
        order_type="MARKET_PAPER",
        reference_price=None,
        expected_fill=None,
        idempotency_key=idem,
        signal_key="signal-btc-governor",
        position_key="btc:daily_swing",
        reserve_cash_usd=None,
        reserve_margin_usd=None,
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        exit_plan_id="exit-btc-governor",
        submit_timeout_at=None,
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-btc-governor",
        created_at_utc=T0,
        event_id="evt-admission-btc-governor",
        actor="portfolio",
        risk_cluster_id="crypto",
        cluster_by_asset={"btc": "crypto"},
        current_observations={},
    )


@pytest.mark.parametrize(
    ("scope_type", "scope_id", "expected_reason"),
    (
        ("route", "btc:daily_swing:long", "route_halted"),
        ("venue", "Kraken", "venue_halted"),
        ("product", "btc", "lifecycle_ineligible"),
        ("desk", None, "desk_halted"),
    ),
)
def test_matching_governor_halt_vetoes_new_risk_before_reserve(
    scope_type: str,
    scope_id: str | None,
    expected_reason: str,
) -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _set(
            conn,
            store,
            scope_key=f"{scope_type}:halt",
            scope_type=scope_type,
            scope_id=scope_id,
            event_id=f"evt-{scope_type}-halt",
        )
        result = _reserve(conn, store)
        assert result["ok"] is False
        assert result["reject_code"] == expected_reason
        assert result["state"] == "REJECTED"

        ticket = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id
                == "ticket-btc-governor"
            )
        ).mappings().one()
        assert ticket["first_killed_by"] == "Governor"
        assert ticket["first_kill_reason"] == expected_reason

        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one() == 0


def test_unrelated_scope_halt_does_not_block_candidate() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _set(
            conn,
            store,
            scope_key="route:other",
            scope_type="route",
            scope_id="eth:daily_swing:long",
            event_id="evt-route-other",
        )
        result = _reserve(conn, store)
        assert result["ok"] is True
        assert result["state"] == "RESERVED"


def test_governor_halt_survives_restart_snapshot_without_auto_reset() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        state = _set(
            conn,
            store,
            scope_key="desk:firm",
            scope_type="desk",
            scope_id=None,
            event_id="evt-desk-halt",
        )
        assert state["state"] == "HALT"
        assert state["row_version"] == 1

    with engine.begin() as conn:
        first = load_restart_snapshot(conn, store=store)
        second = load_restart_snapshot(conn, store=store)

    assert len(first.governor_state) == 1
    assert first.governor_state[0]["state"] == "HALT"
    assert second.governor_state[0]["state"] == "HALT"
    assert second.governor_state[0]["row_version"] == 1


def test_reset_requires_authenticated_actor_and_is_audited() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _set(
            conn,
            store,
            scope_key="route:btc",
            scope_type="route",
            scope_id="btc:daily_swing:long",
            event_id="evt-route-halt",
        )

    with pytest.raises(PermissionError, match="authenticated actor"):
        with engine.begin() as conn:
            _set(
                conn,
                store,
                scope_key="route:btc",
                scope_type="route",
                scope_id="btc:daily_swing:long",
                state="NORMAL",
                expected_row_version=1,
                authenticated=False,
                event_id="evt-route-bad-reset",
            )

    with engine.begin() as conn:
        reset = _set(
            conn,
            store,
            scope_key="route:btc",
            scope_type="route",
            scope_id="btc:daily_swing:long",
            state="NORMAL",
            expected_row_version=1,
            authenticated=True,
            event_id="evt-route-reset",
        )
        assert reset["state"] == "NORMAL"
        assert reset["row_version"] == 2

        events = conn.execute(
            sa.select(store.tables["event_ledger"]).where(
                store.tables["event_ledger"].c.aggregate_id == "route:btc"
            )
        ).mappings().all()
        assert [row["new_state"] for row in events] == ["HALT", "NORMAL"]
        assert events[-1]["reason_code"] == "governor_reset"


def test_governor_optimistic_version_prevents_stale_reset() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _set(
            conn,
            store,
            scope_key="venue:kraken",
            scope_type="venue",
            scope_id="Kraken",
            event_id="evt-venue-halt",
        )

    with pytest.raises(RuntimeError, match="optimistic version mismatch"):
        with engine.begin() as conn:
            _set(
                conn,
                store,
                scope_key="venue:kraken",
                scope_type="venue",
                scope_id="Kraken",
                state="NORMAL",
                expected_row_version=0,
                event_id="evt-venue-stale-reset",
            )
