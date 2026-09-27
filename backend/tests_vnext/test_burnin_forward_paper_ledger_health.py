from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from aether_vnext.burnin_readiness import blocker_class
from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_health import forward_paper_ledger_blockers
from aether_vnext.forward_paper_start import (
    ForwardPaperRouteRequest,
    _start_forward_paper_campaign_for_requests,
)
from tests_vnext.held_out_support import record_provenanced_held_out
from tests_vnext.test_forward_paper_start import T0, _store, _window


def _start_campaign(conn, store, *, campaign_id: str):
    record_provenanced_held_out(
        conn,
        store,
        _window(f"{campaign_id}-heldout"),
    )
    return _start_forward_paper_campaign_for_requests(
        conn,
        store,
        campaign_id=campaign_id,
        requested_routes=(
            ForwardPaperRouteRequest(
                route_id="eurusd:intraday:long",
                playbook_id="pb_fx_intraday_v1_2",
            ),
        ),
        started_at_utc=T0,
        created_at_utc=T0,
    )


def test_forward_paper_ledger_health_accepts_intact_campaign() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        _start_campaign(conn, store, campaign_id="burnin-health-clean")
        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id="burnin-health-clean",
        )

    assert blockers == ()


def test_forward_paper_ledger_health_detects_frozen_baseline_drift() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        _start_campaign(conn, store, campaign_id="burnin-health-baseline")
        campaigns = store.tables["forward_paper_campaigns"]
        conn.execute(
            campaigns.update()
            .where(campaigns.c.campaign_id == "burnin-health-baseline")
            .values(baseline_snapshot_hash="tampered-baseline")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id="burnin-health-baseline",
        )

    assert blockers == (
        "forward_paper_ledger:baseline_snapshot_mismatch",
    )
    assert blocker_class(blockers[0]) == "empirical_evidence"


def test_forward_paper_ledger_health_detects_window_family_drift() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id="burnin-health-window",
        )
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-window-paper",
            route_id="usdjpy:intraday:long",
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(hours=1),
            last_timestamp_utc=T0 + timedelta(hours=2),
            n=1,
            immutable_trade_ids=("health-window-trade",),
            metrics_snapshot_hash="health-window-metrics",
            created_at_utc=T0 + timedelta(hours=3),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-window-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id="burnin-health-window",
        )

    assert blockers == (
        "forward_paper_ledger:window_family_mismatch:"
        "burnin-health-window-paper",
    )
    assert blocker_class(blockers[0]) == "empirical_evidence"



def test_forward_paper_ledger_health_revalidates_immutable_trade_lineage() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id="burnin-health-lineage",
        )
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-lineage-paper",
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(hours=1),
            last_timestamp_utc=T0 + timedelta(hours=2),
            n=1,
            immutable_trade_ids=("missing-canonical-closed-trade",),
            metrics_snapshot_hash="burnin-health-lineage-metrics",
            created_at_utc=T0 + timedelta(hours=3),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-lineage-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id="burnin-health-lineage",
        )

    assert blockers == (
        "forward_paper_ledger:missing_closed_trade_lineage:"
        "burnin-health-lineage-paper:missing-canonical-closed-trade",
    )
    assert blocker_class(blockers[0]) == "empirical_evidence"



def test_forward_paper_ledger_health_recomputes_historical_baseline_hash() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-heldout-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        window_id = result.routes[0].historical_validation_window_ids[0]
        evidence = store.tables["evidence_windows"]
        conn.execute(
            evidence.update()
            .where(evidence.c.evidence_window_id == window_id)
            .values(metrics_snapshot_hash="tampered-heldout-metrics")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    provenance_blocker = (
        "forward_paper_ledger:historical_provenance_hash_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    baseline_blocker = (
        "forward_paper_ledger:historical_baseline_hash_mismatch:"
        + result.routes[0].campaign_route_id
    )
    assert blockers == (provenance_blocker, baseline_blocker)
    assert blocker_class(provenance_blocker) == "empirical_evidence"
    assert blocker_class(baseline_blocker) == "empirical_evidence"



def test_forward_paper_ledger_health_revalidates_research_provenance_chain() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-provenance-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        window_id = result.routes[0].historical_validation_window_ids[0]
        provenance = conn.execute(
            sa.select(store.tables["held_out_evidence_provenance"]).where(
                store.tables["held_out_evidence_provenance"].c.evidence_window_id
                == window_id
            )
        ).mappings().one()

        conn.execute(
            store.tables["backtest_runs"].update()
            .where(
                store.tables["backtest_runs"].c.backtest_run_id
                == provenance["backtest_run_id"]
            )
            .values(configuration_hash="tampered-research-config")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_provenance_run_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"


def test_forward_paper_ledger_health_recomputes_provenance_hash() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-provenance-hash"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        window_id = result.routes[0].historical_validation_window_ids[0]
        provenance = store.tables["held_out_evidence_provenance"]
        conn.execute(
            provenance.update()
            .where(provenance.c.evidence_window_id == window_id)
            .values(provenance_hash="tampered-provenance-hash")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_provenance_hash_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"
