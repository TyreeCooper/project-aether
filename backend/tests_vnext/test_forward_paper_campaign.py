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
