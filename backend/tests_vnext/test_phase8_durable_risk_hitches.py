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
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 21, 20, tzinfo=UTC)


def _store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        store.provision_seed_ledgers_once(conn)
        store.record_market_observation(
            conn,
            MarketObservation(
                observation_id="obs-hitch",
                asset_id="eth",
                venue="Kraken",
                bid=3999.0,
                ask=4001.0,
                last=4000.0,
                mark=4000.0,
                source="test",
                exchange_ts=T0,
                received_ts=T0,
                age_ms=0,
                spread_abs=2.0,
                spread_bps=5.0,
                session_state=SessionState.ACTIVE,
                quality_state=QualityState.HEALTHY,
                fallback_reason=None,
                calendar_state=CalendarState.ALWAYS_OPEN,
                data_version="test-v1",
            ),
        )
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-hitch",
                policy_version="policy-hitch",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="hitch persistence",
                payload={},
                created_at_utc=T0,
            )
        )
    return engine, store


def _lineage(conn, store: VNextStore, *, event_id: str = "firm-eth") -> None:
    conn.execute(
        store.tables["decision_lineage"].insert().values(
            firm_event_id=event_id,
            setup_id="setup-eth",
            ticket_id="ticket-eth",
            order_intent_id=None,
            trade_id=None,
            asset_id="eth",
            route_id="eth:daily_swing:long",
            playbook_id="pb_eth_rider_v1_2",
            playbook_version="1.2",
            risk_cluster_id="crypto",
            asset_risk_hitches={"btc": 0.50},
            policy_version="policy-hitch",
            configuration_hash="cfg-hitch",
            market_observation_id="obs-hitch",
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
            row_version=1,
        )
    )


def _pending(conn, store: VNextStore) -> None:
    _lineage(conn, store)
    conn.execute(
        store.tables["tickets"].insert().values(
            ticket_id="ticket-eth",
            exit_plan_id=None,
            setup_id="setup-eth",
            firm_event_id="firm-eth",
            asset_id="eth",
            route_id="eth:daily_swing:long",
            state="READY",
            signal_key="signal-eth",
            side="long",
            horizon="daily_swing",
            stop_price=3900.0,
            quantity=0.4,
            modeled_round_trip_cost_pct=0.5,
            reject_code=None,
            policy_version="policy-hitch",
            configuration_hash="cfg-hitch",
            market_observation_id="obs-hitch",
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["order_intents"].insert().values(
            order_intent_id="intent-eth",
            broker_account_id="kraken_paper",
            exit_plan_id=None,
            intent_kind="OPEN",
            exit_reason=None,
            position_key="eth:daily_swing",
            signal_key="signal-eth",
            reserved_cash_usd=100.0,
            reserved_margin_usd=0.0,
            ready_spread_bps=2.0,
            hard_stop_price=3900.0,
            submit_timeout_at=T0,
            observation_id_at_fill=None,
            trade_id=None,
            version=1,
            ticket_id="ticket-eth",
            firm_event_id="firm-eth",
            asset_id="eth",
            route_id="eth:daily_swing:long",
            broker="Kraken",
            venue="Kraken",
            symbol_executed="ETHUSD",
            side="long",
            requested_qty=0.4,
            order_type="MARKET_PAPER",
            reference_price=4000.0,
            expected_fill_price=4002.0,
            state="RESERVED",
            submitted_at=None,
            acknowledged_at=None,
            filled_at=None,
            filled_qty=0.0,
            avg_fill_price=None,
            reject_code=None,
            slip_usd=None,
            slip_bps=None,
            idempotency_key="idem-eth",
            policy_version="policy-hitch",
            configuration_hash="cfg-hitch",
            observation_id_at_reserve="obs-hitch",
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["risk_admission_reservations"].insert().values(
            order_intent_id="intent-eth",
            asset_id="eth",
            cluster_id="crypto",
            stop_risk_usd=40.0,
            policy_version="policy-hitch",
            configuration_hash="cfg-hitch",
            created_at_utc=T0,
        )
    )


def test_pending_eth_hitch_survives_as_btc_asset_occupancy_only() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        _pending(conn, store)
        btc = store._pending_open_risk_exposure(
            conn, asset_id="btc", cluster_id="crypto"
        )
        eth = store._pending_open_risk_exposure(
            conn, asset_id="eth", cluster_id="crypto"
        )
    assert btc.asset_open_risk_usd == pytest.approx(20.0)
    assert btc.cluster_open_risk_usd == pytest.approx(40.0)
    assert btc.portfolio_open_risk_usd == pytest.approx(40.0)
    assert eth.asset_open_risk_usd == pytest.approx(40.0)


def test_pending_hitch_drift_fails_closed_and_is_visible_to_reconciliation() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        _pending(conn, store)
        conn.execute(
            store.tables["decision_lineage"].update()
            .where(
                store.tables["decision_lineage"].c.firm_event_id == "firm-eth"
            )
            .values(asset_risk_hitches={})
        )
        issues = store.risk_admission_reconciliation_issues(conn)
        assert issues == (
            "risk_reservation_hitch_mismatch:intent-eth",
        )
        with pytest.raises(RuntimeError, match="Risk hitch drift"):
            store._pending_open_risk_exposure(
                conn, asset_id="btc", cluster_id="crypto"
            )


def test_open_trade_reconstructs_hitch_from_durable_lineage_after_restart() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        _lineage(conn, store)
        conn.execute(
            store.tables["open_trades"].insert().values(
                trade_id="trade-eth",
                order_intent_id="intent-eth",
                ticket_id="ticket-eth",
                setup_id="setup-eth",
                exit_plan_id="exit-eth",
                firm_event_id="firm-eth",
                asset_id="eth",
                route_id="eth:daily_swing:long",
                position_key="eth:daily_swing",
                side="long",
                quantity=0.4,
                avg_entry_price=4000.0,
                initial_stop_risk_usd=40.0,
                exit_plan_version="v1",
                exit_plan_payload={
                    "hard_stop_price": 3900.0,
                    "trailing_policy": {"never_loosen": True},
                },
                management_telemetry={},
                policy_version="policy-hitch",
                configuration_hash="cfg-hitch",
                market_observation_id="obs-hitch",
                opened_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["active_positions"].insert().values(
                position_key="eth:daily_swing",
                trade_id="trade-eth",
                asset_id="eth",
                horizon="daily_swing",
                side="long",
                quantity=0.4,
                row_version=1,
                updated_at_utc=T0,
            )
        )
        snapshot = store.project_open_risk(
            conn,
            cluster_by_asset={"eth": "crypto", "btc": "crypto"},
        )
    by_asset = {row.key: row.stop_risk_usd for row in snapshot.by_asset}
    assert by_asset == pytest.approx({"eth": 40.0, "btc": 20.0})
    assert snapshot.portfolio_open_risk_usd == pytest.approx(40.0)
    assert {
        row.key: row.stop_risk_usd for row in snapshot.by_cluster
    } == pytest.approx({"crypto": 40.0})
