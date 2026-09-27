from __future__ import annotations

from datetime import datetime, timedelta, timezone

import inspect

import pytest
import sqlalchemy as sa

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_preflight import (
    preflight_forward_paper_campaign_from_book,
)
from aether_vnext.forward_paper_start import (
    ForwardPaperRouteRequest,
    _persist_forward_paper_campaign_from_preflight,
    _start_forward_paper_campaign_for_requests,
    start_forward_paper_campaign_from_book,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.store import VNextStore
from tests_vnext.held_out_support import record_provenanced_held_out
from tests_vnext.runtime_registry_support import record_test_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 55, tzinfo=UTC)

def test_operator_start_api_does_not_accept_caller_route_subset() -> None:
    params = inspect.signature(start_forward_paper_campaign_from_book).parameters
    assert "requested_routes" not in params




def _window(
    window_id: str,
    *,
    route_id: str = "eurusd:intraday:long",
    playbook_id: str = "pb_fx_intraday_v1_2",
    playbook_version: str = "1.2",
    configuration_hash: str = CONFIGURATION_HASH,
    policy_version: str = "burnin-policy-v1",
    offset_days: int = 10,
) -> EvidenceWindow:
    first = T0 - timedelta(days=offset_days)
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id=route_id,
        playbook_id=playbook_id,
        playbook_version=playbook_version,
        policy_version=policy_version,
        configuration_hash=configuration_hash,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=first,
        last_timestamp_utc=first + timedelta(days=1),
        n=1,
        immutable_trade_ids=(f"trade:{window_id}",),
        metrics_snapshot_hash=f"metrics:{window_id}",
        created_at_utc=T0 - timedelta(days=1),
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="burnin-policy-v1",
                effective_at_utc=T0 - timedelta(days=30),
                changed_by="test",
                change_reason="burn-in baseline",
                payload={},
                created_at_utc=T0 - timedelta(days=30),
            )
        )
        for asset_id in ("eurusd", "usdjpy"):
            record_test_runtime_binding(
                conn,
                store,
                asset_id=asset_id,
                configuration_hash=CONFIGURATION_HASH,
                now=T0,
            )
    return engine, store


def test_start_freezes_all_current_held_out_windows_for_declared_route() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(conn, store, _window("heldout-1", offset_days=20))
        record_provenanced_held_out(conn, store, _window("heldout-2", offset_days=10))

        result = _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-001",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
            started_at_utc=T0,
            created_at_utc=T0,
        )

        route = conn.execute(
            sa.select(store.tables["forward_paper_campaign_routes"])
        ).mappings().one()
        campaign = conn.execute(
            sa.select(store.tables["forward_paper_campaigns"])
        ).mappings().one()

    assert result.campaign.configuration_hash == CONFIGURATION_HASH
    assert result.campaign.policy_version == "burnin-policy-v1"
    assert result.routes[0].historical_validation_window_ids == (
        "heldout-1",
        "heldout-2",
    )
    assert route["historical_validation_window_ids"] == [
        "heldout-1",
        "heldout-2",
    ]
    assert campaign["baseline_snapshot_hash"] == result.baseline_snapshot_hash
    assert campaign["forced_entry_enabled"] is False
    assert campaign["live_blocked"] is True


def test_baseline_hash_is_deterministic_across_request_order() -> None:
    def build(order: tuple[ForwardPaperRouteRequest, ...]) -> str:
        engine, store = _store()
        with engine.begin() as conn:
            record_provenanced_held_out(conn, store, _window("eurusd-heldout"))
            record_provenanced_held_out(conn, store, _window(
                    "usdjpy-heldout",
                    route_id="usdjpy:intraday:long",
                ),
            )
            result = _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-order-test",
                requested_routes=order,
                started_at_utc=T0,
                created_at_utc=T0,
            )
            return result.baseline_snapshot_hash

    eurusd = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    usdjpy = ForwardPaperRouteRequest(
        route_id="usdjpy:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    assert build((eurusd, usdjpy)) == build((usdjpy, eurusd))


def test_missing_declared_route_baseline_fails_before_campaign_persist() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(conn, store, _window("eurusd-heldout"))
        with pytest.raises(RuntimeError, match="missing_current_held_out_baseline"):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-missing",
                requested_routes=(
                    ForwardPaperRouteRequest(
                        route_id="eurusd:intraday:long",
                        playbook_id="pb_fx_intraday_v1_2",
                    ),
                    ForwardPaperRouteRequest(
                        route_id="usdjpy:intraday:long",
                        playbook_id="pb_fx_intraday_v1_2",
                    ),
                ),
                started_at_utc=T0,
                created_at_utc=T0,
            )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
    assert count == 0


def test_other_configuration_evidence_cannot_satisfy_current_baseline() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="other-config",
                policy_version="other-policy",
                effective_at_utc=T0 - timedelta(days=30),
                changed_by="test",
                change_reason="other",
                payload={},
                created_at_utc=T0 - timedelta(days=30),
            )
        )
        record_provenanced_held_out(conn, store, _window(
                "other-heldout",
                configuration_hash="other-config",
                policy_version="other-policy",
            ),
        )
        with pytest.raises(RuntimeError, match="missing_current_held_out_baseline"):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-config-isolation",
                requested_routes=(
                    ForwardPaperRouteRequest(
                        route_id="eurusd:intraday:long",
                        playbook_id="pb_fx_intraday_v1_2",
                    ),
                ),
                started_at_utc=T0,
                created_at_utc=T0,
            )


def test_benched_playbook_is_not_burnin_eligible() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        with pytest.raises(RuntimeError, match="playbook_not_burnin_eligible"):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-benched",
                requested_routes=(
                    ForwardPaperRouteRequest(
                        route_id="eurusd:scalp:long",
                        playbook_id="pb_fx_scalp_v1_2",
                    ),
                ),
                started_at_utc=T0,
                created_at_utc=T0,
            )


def test_duplicate_route_playbook_request_fails_before_persist() -> None:
    engine, store = _store()
    request = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(conn, store, _window("heldout-1"))
        with pytest.raises(RuntimeError, match="duplicate_route_playbook_request"):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-duplicate",
                requested_routes=(request, request),
                started_at_utc=T0,
                created_at_utc=T0,
            )



def test_campaign_start_retry_reuses_frozen_campaign_without_duplicate_rows() -> None:
    engine, store = _store()
    request = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("retry-heldout"),
        )
        first = _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-retry",
            requested_routes=(request,),
            started_at_utc=T0,
            created_at_utc=T0,
        )
        second = _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-retry",
            requested_routes=(request,),
            started_at_utc=T0 + timedelta(minutes=5),
            created_at_utc=T0 + timedelta(minutes=5),
        )

        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
        route_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_routes"]
            )
        ).scalar_one()

    assert second == first
    assert second.campaign.started_at_utc == T0
    assert second.campaign.created_at_utc == T0
    assert campaign_count == 1
    assert route_count == 1


def test_campaign_id_reuse_refuses_different_route_universe() -> None:
    engine, store = _store()
    eurusd = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    usdjpy = ForwardPaperRouteRequest(
        route_id="usdjpy:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("reuse-eurusd"),
        )
        _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-route-reuse",
            requested_routes=(eurusd,),
            started_at_utc=T0,
            created_at_utc=T0,
        )

        with pytest.raises(
            RuntimeError,
            match="different route universe",
        ):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-route-reuse",
                requested_routes=(usdjpy,),
                started_at_utc=T0 + timedelta(minutes=5),
                created_at_utc=T0 + timedelta(minutes=5),
            )

        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
        route_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_routes"]
            )
        ).scalar_one()

    assert campaign_count == 1
    assert route_count == 1



def test_campaign_start_retry_fails_closed_on_persisted_baseline_drift() -> None:
    engine, store = _store()
    request = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("drift-heldout"),
        )
        _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-drift",
            requested_routes=(request,),
            started_at_utc=T0,
            created_at_utc=T0,
        )

        routes = store.tables["forward_paper_campaign_routes"]
        conn.execute(
            routes.update()
            .where(routes.c.campaign_id == "burnin-drift")
            .values(
                historical_metrics_snapshot_hash="tampered-baseline-hash"
            )
        )

        with pytest.raises(
            RuntimeError,
            match="baseline integrity mismatch",
        ):
            _start_forward_paper_campaign_for_requests(
                conn,
                store,
                campaign_id="burnin-drift",
                requested_routes=(request,),
                started_at_utc=T0 + timedelta(minutes=5),
                created_at_utc=T0 + timedelta(minutes=5),
            )

        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
        route_count = conn.execute(
            sa.select(sa.func.count()).select_from(routes)
        ).scalar_one()

    assert campaign_count == 1
    assert route_count == 1



def test_concurrent_start_collision_converges_on_identical_frozen_baseline() -> None:
    engine, store = _store()
    request = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("race-heldout"),
        )
        contender = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="burnin-race",
            requested_routes=(request,),
            as_of_utc=T0,
        )
        assert contender.startable is True

        winner = _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-race",
            requested_routes=(request,),
            started_at_utc=T0,
            created_at_utc=T0,
        )

        replay = _persist_forward_paper_campaign_from_preflight(
            conn,
            store,
            campaign_id="burnin-race",
            preflight=contender,
            started_at_utc=T0 + timedelta(milliseconds=1),
            created_at_utc=T0 + timedelta(milliseconds=1),
        )

        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
        route_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_routes"]
            )
        ).scalar_one()

    assert replay == winner
    assert campaign_count == 1
    assert route_count == 1


def test_concurrent_start_collision_fails_closed_on_different_baseline() -> None:
    engine, store = _store()
    request = ForwardPaperRouteRequest(
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
    )
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("race-old-heldout", offset_days=20),
        )
        _start_forward_paper_campaign_for_requests(
            conn,
            store,
            campaign_id="burnin-race-drift",
            requested_routes=(request,),
            started_at_utc=T0,
            created_at_utc=T0,
        )

        record_provenanced_held_out(
            conn,
            store,
            _window("race-new-heldout", offset_days=10),
        )
        contender = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="burnin-race-drift",
            requested_routes=(request,),
            as_of_utc=T0 + timedelta(minutes=1),
        )
        assert contender.startable is True

        with pytest.raises(
            RuntimeError,
            match="concurrent campaign start baseline mismatch",
        ):
            _persist_forward_paper_campaign_from_preflight(
                conn,
                store,
                campaign_id="burnin-race-drift",
                preflight=contender,
                started_at_utc=T0 + timedelta(minutes=1),
                created_at_utc=T0 + timedelta(minutes=1),
            )

        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()
        route_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaign_routes"]
            )
        ).scalar_one()

    assert campaign_count == 1
    assert route_count == 1
