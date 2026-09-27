from __future__ import annotations

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
