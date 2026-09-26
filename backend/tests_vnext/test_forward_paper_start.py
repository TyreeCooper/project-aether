from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_start import (
    ForwardPaperRouteRequest,
    start_forward_paper_campaign_from_book,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 55, tzinfo=UTC)


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
    return engine, store


def test_start_freezes_all_current_held_out_windows_for_declared_route() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_evidence_window(conn, _window("heldout-1", offset_days=20))
        store.record_evidence_window(conn, _window("heldout-2", offset_days=10))

        result = start_forward_paper_campaign_from_book(
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
            store.record_evidence_window(conn, _window("eurusd-heldout"))
            store.record_evidence_window(
                conn,
                _window(
                    "usdjpy-heldout",
                    route_id="usdjpy:intraday:long",
                ),
            )
            result = start_forward_paper_campaign_from_book(
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
        store.record_evidence_window(conn, _window("eurusd-heldout"))
        with pytest.raises(RuntimeError, match="missing_current_held_out_baseline"):
            start_forward_paper_campaign_from_book(
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
        store.record_evidence_window(
            conn,
            _window(
                "other-heldout",
                configuration_hash="other-config",
                policy_version="other-policy",
            ),
        )
        with pytest.raises(RuntimeError, match="missing_current_held_out_baseline"):
            start_forward_paper_campaign_from_book(
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
            start_forward_paper_campaign_from_book(
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
        store.record_evidence_window(conn, _window("heldout-1"))
        with pytest.raises(RuntimeError, match="duplicate_route_playbook_request"):
            start_forward_paper_campaign_from_book(
                conn,
                store,
                campaign_id="burnin-duplicate",
                requested_routes=(request, request),
                started_at_utc=T0,
                created_at_utc=T0,
            )
