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
from tests_vnext.runtime_registry_support import record_test_runtime_binding


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
        for asset_id in ("eurusd", "usdjpy"):
            record_test_runtime_binding(
                conn,
                store,
                asset_id=asset_id,
                configuration_hash=CONFIGURATION_HASH,
                now=T0,
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
    assert row.runtime_registry_binding_hash
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



def test_preflight_blocks_malformed_persisted_heldout_sample() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("malformed-heldout"),
        )
        conn.execute(
            store.tables["evidence_windows"].update()
            .where(
                store.tables["evidence_windows"].c.evidence_window_id
                == "malformed-heldout"
            )
            .values(immutable_trade_ids="x")
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-malformed-heldout",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert out.route_results[0].blockers == (
        "held_out_provenance_hash_invalid",
        "held_out_window_reload_failed",
    )
    assert "one_or_more_routes_not_startable" in out.blockers



def test_preflight_blocks_malformed_heldout_provenance_shape() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("malformed-provenance"),
        )
        provenance = store.tables["held_out_evidence_provenance"]
        conn.execute(
            provenance.update()
            .where(
                provenance.c.evidence_window_id
                == "malformed-provenance"
            )
            .values(fold_result_ids="fold:malformed-provenance")
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-malformed-provenance",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_baseline_provenance_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None
    assert "one_or_more_routes_not_startable" in out.blockers



def test_preflight_rejects_noncanonical_heldout_provenance_ids() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("noncanonical-provenance-ids"),
        )
        provenance = store.tables["held_out_evidence_provenance"]
        conn.execute(
            provenance.update()
            .where(
                provenance.c.evidence_window_id
                == "noncanonical-provenance-ids"
            )
            .values(
                fold_result_ids=[" fold:noncanonical-provenance-ids "],
            )
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-noncanonical-provenance-ids",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_baseline_provenance_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None


def test_preflight_revalidates_heldout_backtest_run() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("run-drift"),
        )
        provenance = conn.execute(
            sa.select(store.tables["held_out_evidence_provenance"]).where(
                store.tables["held_out_evidence_provenance"].c.evidence_window_id
                == "run-drift"
            )
        ).mappings().one()
        runs = store.tables["backtest_runs"]
        conn.execute(
            runs.update()
            .where(
                runs.c.backtest_run_id
                == provenance["backtest_run_id"]
            )
            .values(run_type="in_sample")
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-run-drift",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_provenance_run_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None



def test_preflight_revalidates_heldout_dataset() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("dataset-drift"),
        )
        provenance = conn.execute(
            sa.select(store.tables["held_out_evidence_provenance"]).where(
                store.tables["held_out_evidence_provenance"].c.evidence_window_id
                == "dataset-drift"
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

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-dataset-drift",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_provenance_dataset_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None



def test_preflight_revalidates_heldout_fold_chain() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("fold-drift"),
        )
        provenance = store.tables["held_out_evidence_provenance"]
        conn.execute(
            provenance.update()
            .where(provenance.c.evidence_window_id == "fold-drift")
            .values(fold_result_ids=["missing-fold"])
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-fold-drift",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_provenance_fold_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None


def test_preflight_recomputes_heldout_provenance_hash() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_provenanced_held_out(
            conn,
            store,
            _window("provenance-hash-drift"),
        )
        provenance = store.tables["held_out_evidence_provenance"]
        conn.execute(
            provenance.update()
            .where(
                provenance.c.evidence_window_id
                == "provenance-hash-drift"
            )
            .values(provenance_hash="tampered-provenance-hash")
        )

        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="preflight-provenance-hash-drift",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
        )

    assert out.startable is False
    assert "held_out_provenance_hash_invalid" in (
        out.route_results[0].blockers
    )
    assert out.route_results[0].route_baseline_hash is None
