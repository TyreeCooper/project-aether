from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.risk import stop_risk_usd
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 19, 20, tzinfo=UTC)


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _insert_trade(
    conn,
    store: VNextStore,
    *,
    trade_id: str,
    asset_id: str,
    side: str,
    quantity: float,
    entry_price: float,
    hard_stop_price: float,
    horizon: str,
    active: bool = True,
    stored_risk_override: float | None = None,
) -> float:
    risk = stop_risk_usd(
        SEED_REGISTRY[asset_id],
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=hard_stop_price,
    )
    position_key = f"{asset_id}:{horizon}"
    conn.execute(
        store.tables["open_trades"].insert().values(
            trade_id=trade_id,
            order_intent_id=f"intent-{trade_id}",
            ticket_id=f"ticket-{trade_id}",
            setup_id=f"setup-{trade_id}",
            exit_plan_id=f"exit-{trade_id}",
            firm_event_id=None,
            asset_id=asset_id,
            route_id=f"{asset_id}:{horizon}:{side}",
            position_key=position_key,
            side=side,
            quantity=quantity,
            avg_entry_price=entry_price,
            initial_stop_risk_usd=(
                risk if stored_risk_override is None else stored_risk_override
            ),
            exit_plan_version="v1",
            exit_plan_payload={
                "hard_stop_price": hard_stop_price,
                "trailing_policy": {"never_loosen": True},
            },
            management_telemetry={},
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id=f"obs-{trade_id}",
            opened_at_utc=T0,
        )
    )
    if active:
        conn.execute(
            store.tables["active_positions"].insert().values(
                position_key=position_key,
                trade_id=trade_id,
                asset_id=asset_id,
                horizon=horizon,
                side=side,
                quantity=quantity,
                row_version=1,
                updated_at_utc=T0,
            )
        )
    return risk


def test_empty_active_book_has_zero_open_risk() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        snapshot = store.project_open_risk(conn, cluster_by_asset={})
    assert snapshot.positions == ()
    assert snapshot.by_asset == ()
    assert snapshot.by_cluster == ()
    assert snapshot.portfolio_open_risk_usd == 0.0


def test_active_book_aggregates_asset_cluster_and_portfolio_stop_risk() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        btc_risk = _insert_trade(
            conn,
            store,
            trade_id="trade-btc",
            asset_id="btc",
            side="long",
            quantity=0.001,
            entry_price=100_000.0,
            hard_stop_price=95_000.0,
            horizon="daily_swing",
        )
        eth_risk = _insert_trade(
            conn,
            store,
            trade_id="trade-eth",
            asset_id="eth",
            side="long",
            quantity=0.10,
            entry_price=4_000.0,
            hard_stop_price=3_800.0,
            horizon="swing",
        )
        snapshot = store.project_open_risk(
            conn,
            cluster_by_asset={"btc": "crypto", "eth": "crypto"},
        )

    assert snapshot.portfolio_open_risk_usd == pytest.approx(
        btc_risk + eth_risk
    )
    by_asset = {row.key: row.stop_risk_usd for row in snapshot.by_asset}
    by_cluster = {row.key: row.stop_risk_usd for row in snapshot.by_cluster}
    assert by_asset["btc"] == pytest.approx(btc_risk)
    assert by_asset["eth"] == pytest.approx(eth_risk)
    assert by_cluster["crypto"] == pytest.approx(btc_risk + eth_risk)

    exposure = snapshot.exposure_for(asset_id="btc", cluster_id="crypto")
    assert exposure.asset_open_risk_usd == pytest.approx(btc_risk)
    assert exposure.cluster_open_risk_usd == pytest.approx(btc_risk + eth_risk)
    assert exposure.portfolio_open_risk_usd == pytest.approx(
        btc_risk + eth_risk
    )


def test_historical_open_trade_without_active_position_does_not_consume_risk() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_trade(
            conn,
            store,
            trade_id="trade-btc-closed",
            asset_id="btc",
            side="long",
            quantity=0.001,
            entry_price=100_000.0,
            hard_stop_price=95_000.0,
            horizon="daily_swing",
            active=False,
        )
        snapshot = store.project_open_risk(conn, cluster_by_asset={})
    assert snapshot.portfolio_open_risk_usd == 0.0
    assert snapshot.positions == ()


def test_missing_cluster_assignment_fails_closed_for_active_asset() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_trade(
            conn,
            store,
            trade_id="trade-btc",
            asset_id="btc",
            side="long",
            quantity=0.001,
            entry_price=100_000.0,
            hard_stop_price=95_000.0,
            horizon="daily_swing",
        )
        with pytest.raises(
            ValueError,
            match="missing canonical cluster assignment for active asset: btc",
        ):
            store.project_open_risk(conn, cluster_by_asset={})


def test_stored_initial_stop_risk_must_match_durable_trade_geometry() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_trade(
            conn,
            store,
            trade_id="trade-btc",
            asset_id="btc",
            side="long",
            quantity=0.001,
            entry_price=100_000.0,
            hard_stop_price=95_000.0,
            horizon="daily_swing",
            stored_risk_override=999.0,
        )
        with pytest.raises(
            RuntimeError,
            match="initial stop-risk drift for trade: trade-btc",
        ):
            store.project_open_risk(
                conn,
                cluster_by_asset={"btc": "crypto"},
            )


def test_active_position_identity_drift_fails_closed() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_trade(
            conn,
            store,
            trade_id="trade-btc",
            asset_id="btc",
            side="long",
            quantity=0.001,
            entry_price=100_000.0,
            hard_stop_price=95_000.0,
            horizon="daily_swing",
        )
        conn.execute(
            store.tables["active_positions"].update().values(quantity=0.002)
        )
        with pytest.raises(
            RuntimeError,
            match="active/OpenTrade quantity drift",
        ):
            store.project_open_risk(
                conn,
                cluster_by_asset={"btc": "crypto"},
            )
