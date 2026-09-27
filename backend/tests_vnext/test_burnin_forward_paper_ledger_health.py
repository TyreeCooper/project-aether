from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

import aether_vnext.forward_paper_health as forward_paper_health_module
from aether_vnext.burnin_readiness import blocker_class
from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_health import forward_paper_ledger_blockers
from aether_vnext.forward_paper_start import (
    ForwardPaperRouteRequest,
    _start_forward_paper_campaign_for_requests,
)
from tests_vnext.held_out_support import record_provenanced_held_out
from tests_vnext.runtime_registry_support import make_runtime_binding
from tests_vnext.test_forward_paper_campaign import _record_closed_trade_lineage
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



def test_forward_paper_ledger_health_dataset_mismatch_is_fail_closed() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-dataset-mismatch"
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

        datasets = store.tables["research_dataset_snapshots"]
        conn.execute(
            datasets.update()
            .where(
                datasets.c.dataset_snapshot_id
                == provenance["dataset_snapshot_id"]
            )
            .values(asset_ids=["usdjpy"])
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_provenance_dataset_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_detects_cross_campaign_route_link_both_sides() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        first = _start_campaign(
            conn,
            store,
            campaign_id="burnin-health-link-a",
        )
        second = _start_campaign(
            conn,
            store,
            campaign_id="burnin-health-link-b",
        )
        route = second.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-cross-link-paper",
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=second.campaign.policy_version,
            configuration_hash=second.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(hours=1),
            last_timestamp_utc=T0 + timedelta(hours=2),
            n=1,
            immutable_trade_ids=("burnin-health-cross-link-trade",),
            metrics_snapshot_hash="burnin-health-cross-link-metrics",
            created_at_utc=T0 + timedelta(hours=3),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-cross-link",
                campaign_id=first.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )

        first_blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=first.campaign.campaign_id,
        )
        second_blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=second.campaign.campaign_id,
        )

    expected = (
        "forward_paper_ledger:cross_campaign_route_link:"
        "burnin-health-cross-link"
    )
    assert expected in first_blockers
    assert expected in second_blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_detects_persisted_policy_lineage_drift() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-policy-lineage"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        trade_id = "trade-health-policy-lineage"
        _record_closed_trade_lineage(
            conn,
            store,
            trade_id=trade_id,
            lineage_policy_version="old-policy",
        )
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-policy-lineage-paper",
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(minutes=1),
            last_timestamp_utc=T0 + timedelta(hours=1),
            n=1,
            immutable_trade_ids=(trade_id,),
            metrics_snapshot_hash="burnin-health-policy-lineage-metrics",
            created_at_utc=T0 + timedelta(hours=2),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-policy-lineage-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:trade_lineage_mismatch:"
        + window.evidence_window_id
        + ":"
        + trade_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_detects_evidence_before_trade_close() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-trade-chronology"
    trade_id = "trade-health-after-evidence"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
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
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-trade-chronology-paper",
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(minutes=1),
            last_timestamp_utc=T0 + timedelta(hours=1),
            n=1,
            immutable_trade_ids=(trade_id,),
            metrics_snapshot_hash="burnin-health-trade-chronology-metrics",
            created_at_utc=T0 + timedelta(hours=2),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-trade-chronology-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=4),
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:evidence_predates_trade_close:"
        + window.evidence_window_id
        + ":"
        + trade_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_detects_runtime_binding_drift() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-runtime-binding-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        drifted_binding = replace(
            make_runtime_binding("eurusd", now=T0),
            broker_symbol="EURUSD-DRIFT",
        )
        store.upsert_runtime_registry_binding(
            conn,
            drifted_binding,
            registry_version="test-runtime-registry-v2",
            configuration_hash=result.campaign.configuration_hash,
            updated_at_utc=T0 + timedelta(hours=1),
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:runtime_binding_hash_mismatch:"
        + result.routes[0].campaign_route_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "external_runtime_configuration"



def test_forward_paper_ledger_health_detects_lineage_key_drift() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-lineage-key-drift"
    trade_id = "trade-health-lineage-key-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
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
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id="burnin-health-lineage-key-paper",
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(minutes=1),
            last_timestamp_utc=T0 + timedelta(hours=1),
            n=1,
            immutable_trade_ids=(trade_id,),
            metrics_snapshot_hash="burnin-health-lineage-key-metrics",
            created_at_utc=T0 + timedelta(hours=2),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-lineage-key-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:trade_lineage_mismatch:"
        + window.evidence_window_id
        + ":"
        + trade_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_rederives_campaign_route_id() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-route-id-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        original_route_id = result.routes[0].campaign_route_id
        route_table = store.tables["forward_paper_campaign_routes"]
        tampered_route_id = "tampered-campaign-route-id"
        conn.execute(
            route_table.update()
            .where(route_table.c.campaign_route_id == original_route_id)
            .values(campaign_route_id=tampered_route_id)
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:campaign_route_id_mismatch:"
        + tampered_route_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_revalidates_campaign_safety_root() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-campaign-safety-drift"
    with engine.begin() as conn:
        _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        conn.execute(sa.text("PRAGMA ignore_check_constraints = ON"))
        try:
            conn.execute(
                store.tables["forward_paper_campaigns"].update()
                .where(
                    store.tables["forward_paper_campaigns"].c.campaign_id
                    == campaign_id
                )
                .values(live_blocked=False)
            )

            blockers = forward_paper_ledger_blockers(
                conn,
                store=store,
                campaign_id=campaign_id,
            )
        finally:
            conn.execute(sa.text("PRAGMA ignore_check_constraints = OFF"))

    expected = "forward_paper_ledger:campaign_safety_invariant_mismatch"
    assert expected in blockers
    assert blocker_class(expected) == "safety_invariant"


def test_forward_paper_ledger_health_revalidates_campaign_policy_root() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-campaign-policy-drift"
    with engine.begin() as conn:
        _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        conn.execute(
            store.tables["forward_paper_campaigns"].update()
            .where(
                store.tables["forward_paper_campaigns"].c.campaign_id
                == campaign_id
            )
            .values(policy_version="tampered-policy-version")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = "forward_paper_ledger:campaign_policy_snapshot_mismatch"
    assert expected in blockers
    assert blocker_class(expected) == "environment_initialization"



def test_forward_paper_ledger_health_revalidates_current_playbook_source(
    monkeypatch,
) -> None:
    engine, store = _store()
    campaign_id = "burnin-health-source-playbook-drift"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        route = result.routes[0]
        current_spec = forward_paper_health_module.playbook(route.playbook_id)
        drifted_spec = replace(
            current_spec,
            version="9.9",
        )
        monkeypatch.setattr(
            forward_paper_health_module,
            "playbook",
            lambda playbook_id: (
                drifted_spec
                if playbook_id == route.playbook_id
                else forward_paper_health_module.playbook(playbook_id)
            ),
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:source_playbook_mismatch:"
        + route.campaign_route_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "source_authority"



@pytest.mark.parametrize("malformed_trade_ids", ("x", [" x "]))
def test_forward_paper_ledger_health_rejects_malformed_trade_id_payload(
    malformed_trade_ids: object,
) -> None:
    engine, store = _store()
    campaign_id = "burnin-health-scalar-trade-ids"
    window_id = "burnin-health-scalar-trade-ids-paper"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id=window_id,
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(minutes=1),
            last_timestamp_utc=T0 + timedelta(hours=1),
            n=1,
            immutable_trade_ids=("x",),
            metrics_snapshot_hash="burnin-health-scalar-trade-ids-metrics",
            created_at_utc=T0 + timedelta(hours=2),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-scalar-trade-ids-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )
        conn.execute(
            store.tables["evidence_windows"].update()
            .where(
                store.tables["evidence_windows"].c.evidence_window_id
                == window_id
            )
            .values(immutable_trade_ids=malformed_trade_ids)
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:window_trade_sample_invalid:"
        + window_id
    )
    assert expected in blockers
    assert not any(
        blocker.startswith(
            "forward_paper_ledger:missing_closed_trade_lineage:"
            + window_id
            + ":"
        )
        for blocker in blockers
    )


def test_forward_paper_ledger_health_rejects_non_integer_sample_n() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-invalid-sample-n"
    window_id = "burnin-health-invalid-sample-n-paper"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        route = result.routes[0]
        window = EvidenceWindow(
            evidence_window_id=window_id,
            route_id=route.route_id,
            playbook_id=route.playbook_id,
            playbook_version=route.playbook_version,
            policy_version=result.campaign.policy_version,
            configuration_hash=result.campaign.configuration_hash,
            sample_domain=SampleDomain.PAPER_FORWARD,
            first_timestamp_utc=T0 + timedelta(minutes=1),
            last_timestamp_utc=T0 + timedelta(hours=1),
            n=1,
            immutable_trade_ids=("x",),
            metrics_snapshot_hash="burnin-health-invalid-sample-n-metrics",
            created_at_utc=T0 + timedelta(hours=2),
        )
        store._record_evidence_window_row(conn, window)
        conn.execute(
            store.tables["forward_paper_campaign_windows"].insert().values(
                campaign_window_id="burnin-health-invalid-sample-n-link",
                campaign_id=result.campaign.campaign_id,
                campaign_route_id=route.campaign_route_id,
                evidence_window_id=window.evidence_window_id,
                linked_at_utc=T0 + timedelta(hours=3),
            )
        )
        conn.execute(
            sa.text(
                "UPDATE evidence_windows "
                "SET n = 'not-an-integer' "
                "WHERE evidence_window_id = :window_id"
            ),
            {"window_id": window_id},
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:window_trade_sample_invalid:"
        + window_id
    )
    assert expected in blockers



def test_forward_paper_ledger_health_rejects_scalar_fold_id_payload() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-scalar-fold-ids"
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
            .values(fold_result_ids=f"fold:{window_id}")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_provenance_fold_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"


def test_forward_paper_ledger_health_rejects_scalar_dataset_asset_ids() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-scalar-dataset-assets"
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
        datasets = store.tables["research_dataset_snapshots"]
        conn.execute(
            datasets.update()
            .where(
                datasets.c.dataset_snapshot_id
                == provenance["dataset_snapshot_id"]
            )
            .values(asset_ids="eurusd")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_provenance_dataset_mismatch:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



@pytest.mark.parametrize("malformed_trade_ids", ("x", [" x "]))
def test_forward_paper_ledger_health_rejects_malformed_heldout_trade_ids(
    malformed_trade_ids: object,
) -> None:
    engine, store = _store()
    campaign_id = "burnin-health-scalar-heldout-trades"
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
            .values(immutable_trade_ids=malformed_trade_ids)
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = (
        "forward_paper_ledger:historical_baseline_sample_invalid:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"


def test_forward_paper_ledger_health_rejects_non_integer_heldout_n() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-invalid-heldout-n"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        window_id = result.routes[0].historical_validation_window_ids[0]
        conn.execute(sa.text("PRAGMA ignore_check_constraints = ON"))
        try:
            conn.execute(
                sa.text(
                    "UPDATE evidence_windows "
                    "SET n = 'not-an-integer' "
                    "WHERE evidence_window_id = :window_id"
                ),
                {"window_id": window_id},
            )

            blockers = forward_paper_ledger_blockers(
                conn,
                store=store,
                campaign_id=campaign_id,
            )
        finally:
            conn.execute(sa.text("PRAGMA ignore_check_constraints = OFF"))

    expected = (
        "forward_paper_ledger:historical_baseline_sample_invalid:"
        + result.routes[0].campaign_route_id
        + ":"
        + window_id
    )
    assert expected in blockers
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_rejects_scalar_route_baseline_ids() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-route-baseline-json"
    with engine.begin() as conn:
        result = _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        route_id = result.routes[0].campaign_route_id
        conn.execute(
            store.tables["forward_paper_campaign_routes"].update()
            .where(
                store.tables["forward_paper_campaign_routes"].c.campaign_route_id
                == route_id
            )
            .values(historical_validation_window_ids="heldout-scalar")
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    expected = "forward_paper_ledger:invalid_route_baseline:" + route_id
    assert blockers == (expected,)
    assert blocker_class(expected) == "empirical_evidence"



def test_forward_paper_ledger_health_preserves_root_blockers_without_routes() -> None:
    engine, store = _store()
    campaign_id = "burnin-health-no-routes-root-drift"
    with engine.begin() as conn:
        _start_campaign(
            conn,
            store,
            campaign_id=campaign_id,
        )
        conn.execute(
            store.tables["forward_paper_campaigns"].update()
            .where(
                store.tables["forward_paper_campaigns"].c.campaign_id
                == campaign_id
            )
            .values(policy_version="tampered-policy-version")
        )
        conn.execute(
            store.tables["forward_paper_campaign_routes"].delete().where(
                store.tables["forward_paper_campaign_routes"].c.campaign_id
                == campaign_id
            )
        )

        blockers = forward_paper_ledger_blockers(
            conn,
            store=store,
            campaign_id=campaign_id,
        )

    assert blockers == (
        "forward_paper_ledger:campaign_policy_snapshot_mismatch",
        "forward_paper_ledger:campaign_has_no_routes",
    )
    assert blocker_class(blockers[0]) == "environment_initialization"
    assert blocker_class(blockers[1]) == "empirical_evidence"
