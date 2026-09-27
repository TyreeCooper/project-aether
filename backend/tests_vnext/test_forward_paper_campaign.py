from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper import (
    ForwardPaperCampaign,
    ForwardPaperRouteBaseline,
)
from aether_vnext.store import VNextStore
from tests_vnext.held_out_support import record_provenanced_held_out
from tests_vnext.runtime_registry_support import (
    make_runtime_binding,
    record_test_runtime_binding,
    runtime_binding_hash,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 30, tzinfo=UTC)


def _campaign() -> ForwardPaperCampaign:
    return ForwardPaperCampaign(
        campaign_id="fp-001",
        configuration_hash="cfg-fp",
        policy_version="policy-fp",
        baseline_snapshot_hash="baseline-fp-001",
        started_at_utc=T0,
        created_at_utc=T0,
    )


def _window(
    *,
    window_id: str,
    domain: SampleDomain,
    trade_ids: tuple[str, ...],
    first_at: datetime = T0,
) -> EvidenceWindow:
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="policy-fp",
        configuration_hash="cfg-fp",
        sample_domain=domain,
        first_timestamp_utc=first_at,
        last_timestamp_utc=first_at + timedelta(hours=1),
        n=len(trade_ids),
        immutable_trade_ids=trade_ids,
        metrics_snapshot_hash=f"metrics:{window_id}",
        created_at_utc=first_at + timedelta(hours=2),
    )


def _route() -> ForwardPaperRouteBaseline:
    return ForwardPaperRouteBaseline(
        campaign_route_id="fp-001:eurusd:intraday:long:pb_fx_intraday_v1_2",
        campaign_id="fp-001",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        configuration_hash="cfg-fp",
        runtime_registry_binding_hash=runtime_binding_hash(
            "eurusd",
            now=T0,
        ),
        historical_validation_window_ids=("heldout-1",),
        historical_metrics_snapshot_hash="historical-metrics-1",
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-fp",
                policy_version="policy-fp",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="forward-paper",
                payload={},
                created_at_utc=T0,
            )
        )
        record_test_runtime_binding(
            conn,
            store,
            asset_id="eurusd",
            configuration_hash="cfg-fp",
            now=T0,
        )
        record_provenanced_held_out(conn, store, _window(
                window_id="heldout-1",
                domain=SampleDomain.HELD_OUT,
                trade_ids=("hist-1",),
                first_at=T0 - timedelta(days=10),
            ),
        )
    return engine, store




def _record_closed_trade_lineage(
    conn,
    store,
    *,
    trade_id: str,
    closed_policy_version: str = "policy-fp",
    lineage_policy_version: str = "policy-fp",
    setup_policy_version: str = "policy-fp",
) -> None:
    firm_event_id = f"firm:{trade_id}"
    setup_id = f"setup:{trade_id}"
    conn.execute(
        store.tables["decision_lineage"].insert().values(
            firm_event_id=firm_event_id,
            setup_id=setup_id,
            trade_id=trade_id,
            asset_id="eurusd",
            route_id="eurusd:intraday:long",
            playbook_id="pb_fx_intraday_v1_2",
            playbook_version="1.2",
            policy_version=lineage_policy_version,
            configuration_hash="cfg-fp",
            created_at_utc=T0 + timedelta(minutes=1),
            row_version=1,
        )
    )
    conn.execute(
        store.tables["setups"].insert().values(
            setup_id=setup_id,
            firm_event_id=firm_event_id,
            asset_id="eurusd",
            route_id="eurusd:intraday:long",
            state="FIRE",
            side="long",
            horizon="intraday",
            playbook_id="pb_fx_intraday_v1_2",
            playbook_version="1.2",
            risk_cluster_id="fx",
            asset_risk_hitches=[],
            trigger_bar_close_exchange_ts=T0 + timedelta(minutes=1),
            exit_contract_complete=True,
            intel_pack={},
            policy_version=setup_policy_version,
            configuration_hash="cfg-fp",
            market_observation_id=f"obs:{trade_id}",
            created_at_utc=T0 + timedelta(minutes=1),
        )
    )
    conn.execute(
        store.tables["closed_trades"].insert().values(
            trade_id=trade_id,
            firm_event_id=firm_event_id,
            route_id="eurusd:intraday:long",
            asset_id="eurusd",
            position_key="eurusd:intraday",
            side="long",
            quantity=1.0,
            avg_entry_price=1.1,
            exit_price=1.2,
            closed_at_utc=T0 + timedelta(hours=1),
            gross_pnl_usd=1.0,
            net_pnl_usd=0.9,
            total_cost_usd=0.1,
            fees_usd=0.1,
            duration_s=60.0,
            exit_reason="structure",
            regime_tags=[],
            policy_version=closed_policy_version,
            configuration_hash="cfg-fp",
            market_observation_id=f"obs:{trade_id}",
        )
    )

def test_campaign_contract_hard_locks_c91_safety_invariants() -> None:
    assert _campaign().forced_entry_enabled is False
    with pytest.raises(ValueError, match="forced entry OFF"):
        ForwardPaperCampaign(
            campaign_id="bad",
            configuration_hash="cfg-fp",
            policy_version="policy-fp",
            baseline_snapshot_hash="baseline",
            started_at_utc=T0,
            created_at_utc=T0,
            forced_entry_enabled=True,
        )
    with pytest.raises(ValueError, match="no_cherry_pick"):
        ForwardPaperCampaign(
            campaign_id="bad2",
            configuration_hash="cfg-fp",
            policy_version="policy-fp",
            baseline_snapshot_hash="baseline",
            started_at_utc=T0,
            created_at_utc=T0,
            no_cherry_pick=False,
        )


def test_campaign_baseline_requires_held_out_same_family_evidence() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        campaign = conn.execute(
            sa.select(store.tables["forward_paper_campaigns"])
        ).mappings().one()
        route = conn.execute(
            sa.select(store.tables["forward_paper_campaign_routes"])
        ).mappings().one()

    assert campaign["forced_entry_enabled"] is False
    assert campaign["live_blocked"] is True
    assert route["historical_validation_window_ids"] == ["heldout-1"]


def test_campaign_rejects_non_held_out_historical_baseline() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        conn.execute(
            store.tables["evidence_windows"].delete().where(
                store.tables["evidence_windows"].c.evidence_window_id
                == "heldout-1"
            )
        )
        store._record_evidence_window_row(
            conn,
            _window(
                window_id="heldout-1",
                domain=SampleDomain.IN_SAMPLE,
                trade_ids=("hist-1",),
                first_at=T0 - timedelta(days=10),
            ),
        )
        with pytest.raises(ValueError, match="must be held_out"):
            store.record_forward_paper_campaign(
                conn,
                _campaign(),
                routes=(_route(),),
            )


def test_paper_forward_window_requires_canonical_closed_trade_lineage() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        with pytest.raises(ValueError, match="ClosedTrade lineage"):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-link-1",
                campaign_route_id=_route().campaign_route_id,
                window=_window(
                    window_id="paper-1",
                    domain=SampleDomain.PAPER_FORWARD,
                    trade_ids=("not-a-real-closed-trade",),
                ),
                linked_at_utc=T0 + timedelta(hours=2),
            )


def test_campaign_route_freezes_playbook_route_and_configuration_identity() -> None:
    engine, store = _store()
    bad = ForwardPaperRouteBaseline(
        campaign_route_id="bad-route",
        campaign_id="fp-001",
        route_id="eurusd:swing:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        configuration_hash="cfg-fp",
        runtime_registry_binding_hash=runtime_binding_hash(
            "eurusd",
            now=T0,
        ),
        historical_validation_window_ids=("heldout-1",),
        historical_metrics_snapshot_hash="historical-metrics-1",
    )
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="horizon mismatch"):
            store.record_forward_paper_campaign(
                conn,
                _campaign(),
                routes=(bad,),
            )



def test_paper_forward_window_exact_replay_is_idempotent() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-replay-1",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-replay-1",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id="trade-replay-1",
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="fp-window-replay-1",
                campaign_id="fp-001",
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=2),
            )
        )

        store.record_forward_paper_evidence_window(
            conn,
            campaign_window_id="fp-window-replay-1",
            campaign_route_id=route.campaign_route_id,
            window=window,
            linked_at_utc=T0 + timedelta(hours=3),
        )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 1


def test_paper_forward_window_replay_fails_closed_on_identity_drift() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-replay-drift",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-replay-drift",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="fp-window-replay-drift",
                campaign_id="fp-001",
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=2),
            )
        )

        drifted = EvidenceWindow(
            evidence_window_id=window.evidence_window_id,
            route_id=window.route_id,
            playbook_id=window.playbook_id,
            playbook_version=window.playbook_version,
            policy_version=window.policy_version,
            configuration_hash=window.configuration_hash,
            sample_domain=window.sample_domain,
            first_timestamp_utc=window.first_timestamp_utc,
            last_timestamp_utc=window.last_timestamp_utc,
            n=window.n,
            immutable_trade_ids=window.immutable_trade_ids,
            metrics_snapshot_hash="tampered-paper-metrics",
            created_at_utc=window.created_at_utc,
        )
        with pytest.raises(
            ValueError,
            match="replay identity mismatch",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-replay-drift",
                campaign_route_id=route.campaign_route_id,
                window=drifted,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 1



def test_paper_forward_exact_replay_rechecks_frozen_route_identity() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-replay-route-drift",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-replay-route-drift",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="fp-window-replay-route-drift",
                campaign_id="fp-001",
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=2),
            )
        )

        conn.execute(
            store.tables["forward_paper_campaign_routes"].update()
            .where(
                store.tables["forward_paper_campaign_routes"].c.campaign_route_id
                == route.campaign_route_id
            )
            .values(configuration_hash="tampered-config")
        )

        with pytest.raises(
            ValueError,
            match="does not match frozen campaign route",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-replay-route-drift",
                campaign_route_id=route.campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 1



def test_paper_forward_orphan_evidence_row_fails_closed() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-orphan-evidence",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-orphan-evidence",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        store._record_evidence_window_row(conn, window)

        with pytest.raises(
            ValueError,
            match="replay identity mismatch",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-orphan-evidence",
                campaign_route_id=route.campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=2),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 0



def test_paper_forward_window_link_timestamp_cannot_precede_evidence() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        window = _window(
            window_id="paper-link-time",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=("trade-link-time",),
        )
        with pytest.raises(
            ValueError,
            match="link cannot predate window end",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-link-time",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(minutes=30),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-link-time"
            )
        ).scalar_one()

    assert evidence_count == 0
    assert link_count == 0



def test_paper_forward_exact_replay_rejects_cross_campaign_link_owner() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-replay-owner-drift",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-replay-owner-drift",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="fp-window-replay-owner-drift",
                campaign_id="foreign-campaign",
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=2),
            )
        )

        with pytest.raises(
            ValueError,
            match="replay identity mismatch",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-replay-owner-drift",
                campaign_route_id=route.campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 1



def test_paper_forward_window_rejects_closed_trade_policy_drift() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id="trade-policy-drift",
            closed_policy_version="old-policy",
        )
        window = _window(
            window_id="paper-policy-drift",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=("trade-policy-drift",),
            first_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(
            ValueError,
            match="ClosedTrade policy mismatch",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-policy-drift",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=4),
            )

        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-policy-drift"
            )
        ).scalar_one()

    assert link_count == 0



def test_paper_forward_window_rejects_trade_closed_before_setup() -> None:
    engine, store = _store()
    trade_id = "trade-close-before-setup"
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id=trade_id,
        )
        conn.execute(
            store.tables["closed_trades"].update()
            .where(store.tables["closed_trades"].c.trade_id == trade_id)
            .values(closed_at_utc=T0)
        )
        window = _window(
            window_id="paper-close-before-setup",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=(trade_id,),
            first_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(
            ValueError,
            match="closes before Setup trigger",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-close-before-setup",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=4),
            )

        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-close-before-setup"
            )
        ).scalar_one()

    assert link_count == 0


def test_paper_forward_window_rejects_evidence_created_before_trade_close() -> None:
    engine, store = _store()
    trade_id = "trade-close-after-evidence"
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id=trade_id,
        )
        conn.execute(
            store.tables["closed_trades"].update()
            .where(store.tables["closed_trades"].c.trade_id == trade_id)
            .values(closed_at_utc=T0 + timedelta(hours=3))
        )
        window = _window(
            window_id="paper-evidence-before-close",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=(trade_id,),
            first_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(
            ValueError,
            match="evidence predates ClosedTrade close",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-evidence-before-close",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=4),
            )

        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-evidence-before-close"
            )
        ).scalar_one()

    assert link_count == 0



def test_paper_forward_exact_replay_revalidates_canonical_trade_lineage() -> None:
    engine, store = _store()
    window = _window(
        window_id="paper-replay-lineage-missing",
        domain=SampleDomain.PAPER_FORWARD,
        trade_ids=("trade-replay-lineage-missing",),
    )
    route = _route()

    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(route,),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="fp-window-replay-lineage-missing",
                campaign_id="fp-001",
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=2),
            )
        )

        with pytest.raises(
            ValueError,
            match="ClosedTrade lineage",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-replay-lineage-missing",
                campaign_route_id=route.campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        evidence_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["evidence_windows"]
            ).where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()
        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.evidence_window_id
                == window.evidence_window_id
            )
        ).scalar_one()

    assert evidence_count == 1
    assert link_count == 1



def test_paper_forward_window_rejects_runtime_binding_drift() -> None:
    engine, store = _store()
    trade_id = "trade-runtime-binding-drift"
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id=trade_id,
        )
        drifted_binding = replace(
            make_runtime_binding("eurusd", now=T0),
            broker_symbol="EURUSD-DRIFT",
        )
        store.upsert_runtime_registry_binding(
            conn,
            drifted_binding,
            registry_version="test-runtime-registry-v2",
            configuration_hash="cfg-fp",
            updated_at_utc=T0 + timedelta(hours=1),
        )
        window = _window(
            window_id="paper-runtime-binding-drift",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=(trade_id,),
            first_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(
            ValueError,
            match="runtime Product Registry binding drift",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-runtime-binding-drift",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-runtime-binding-drift"
            )
        ).scalar_one()

    assert link_count == 0



def test_paper_forward_window_rejects_lineage_trade_id_drift() -> None:
    engine, store = _store()
    trade_id = "trade-lineage-key-drift"
    with engine.begin() as conn:
        store.record_forward_paper_campaign(
            conn,
            _campaign(),
            routes=(_route(),),
        )
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id=trade_id,
        )
        conn.execute(
            store.tables["decision_lineage"].update()
            .where(
                store.tables["decision_lineage"].c.firm_event_id
                == f"firm:{trade_id}"
            )
            .values(trade_id="different-trade")
        )
        window = _window(
            window_id="paper-lineage-key-drift",
            domain=SampleDomain.PAPER_FORWARD,
            trade_ids=(trade_id,),
            first_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(
            ValueError,
            match="lineage key mismatch",
        ):
            store.record_forward_paper_evidence_window(
                conn,
                campaign_window_id="fp-window-lineage-key-drift",
                campaign_route_id=_route().campaign_route_id,
                window=window,
                linked_at_utc=T0 + timedelta(hours=3),
            )

        link_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_windows"]
            ).where(
                store.tables["forward_paper_campaign_windows"].c.campaign_window_id
                == "fp-window-lineage-key-drift"
            )
        ).scalar_one()

    assert link_count == 0
