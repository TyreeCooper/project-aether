from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    preflight_forward_paper_campaign_from_book,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.store import VNextStore
from tests_vnext.held_out_support import record_provenanced_held_out


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 0, 5, tzinfo=UTC)


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
                change_reason="preflight",
                payload={},
                created_at_utc=T0 - timedelta(days=30),
            )
        )
    return engine, store


def _window(
    window_id: str,
    *,
    route_id: str = "eurusd:intraday:long",
    trade_ids: tuple[str, ...] = ("trade-1", "trade-2"),
    offset_days: int = 10,
) -> EvidenceWindow:
    first = T0 - timedelta(days=offset_days)
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id=route_id,
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="burnin-policy-v1",
        configuration_hash=CONFIGURATION_HASH,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=first,
        last_timestamp_utc=first + timedelta(days=1),
        n=len(trade_ids),
        immutable_trade_ids=trade_ids,
        metrics_snapshot_hash=f"metrics:{window_id}",
        created_at_utc=T0 - timedelta(days=1),
    )


def test_preflight_is_read_only_and_reports_exact_coverage() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(conn, store, _window("w1", trade_ids=("trade-1", "trade-2")),
        )
        record_provenanced_held_out(conn, store, _window(
                "w2",
                trade_ids=("trade-2", "trade-3"),
                offset_days=5,
            ),
        )
        before = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-001",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

        after = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()

    assert before == after == 0
    assert out.startable is True
    assert out.policy_version == "burnin-policy-v1"
    assert out.baseline_snapshot_hash
    row = out.route_results[0]
    assert row.held_out_window_ids == ("w1", "w2")
    assert row.held_out_window_count == 2
    assert row.independent_held_out_n == 3
    assert row.blockers == ()


def test_preflight_reports_exact_missing_route_without_writing() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-missing",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="usdjpy:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )
        campaign_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["forward_paper_campaigns"]
            )
        ).scalar_one()

    assert out.startable is False
    assert out.missing_routes == ("usdjpy:intraday:long",)
    assert "one_or_more_routes_not_startable" in out.blockers
    assert out.route_results[0].blockers == (
        "missing_current_held_out_baseline",
    )
    assert campaign_count == 0


def test_preflight_rejects_benched_playbook_as_diagnostic_not_write() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-bench",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:scalp:long",
                    playbook_id="pb_fx_scalp_v1_2",
                ),
            ),
        )
    assert out.startable is False
    assert "playbook_not_burnin_eligible" in out.route_results[0].blockers


def test_preflight_reports_missing_canonical_policy_snapshot() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-no-policy",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )
    assert out.startable is False
    assert "canonical_policy_snapshot_missing" in out.blockers


def test_preflight_rejects_scout_enabled_route_with_incomplete_exit_contract() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-incomplete-exit",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eth:daily_swing:long",
                    playbook_id="pb_eth_rider_v1_2",
                ),
            ),
        )
    assert out.startable is False
    assert out.route_results[0].blockers == ("exit_contract_incomplete",)
