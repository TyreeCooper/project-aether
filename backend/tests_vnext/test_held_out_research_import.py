from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.freeze import CONFIGURATION_HASH, FREEZE_VERSION
from aether_vnext.held_out_import import (
    MANIFEST_VERSION,
    parse_held_out_research_manifest,
    persist_held_out_research_manifest,
)
from aether_vnext.policy_bootstrap import (
    bootstrap_canonical_policy_snapshot,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
HEX64 = "a" * 64
SHA40 = "b" * 40


def _payload() -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "configuration_hash": CONFIGURATION_HASH,
        "policy_version": FREEZE_VERSION,
        "source_ref": "reviewed-real-research-artifact:btc-1",
        "hypotheses": [
            {
                "hypothesis_id": "hyp:btc:daily_swing:long:v1",
                "created_at_utc": (
                    T0 - timedelta(days=100)
                ).isoformat(),
                "hypothesis_text": (
                    "BTC breakout continuation may earn after costs."
                ),
                "economic_rationale": (
                    "Persistent order flow after a structural break."
                ),
                "mechanism_class": "breakout_continuation",
                "eligible_assets": ["btc"],
                "horizon": "daily_swing",
                "allowed_sides": ["long"],
                "expected_regimes": ["trend"],
                "falsification_conditions": [
                    "negative_net_edge"
                ],
                "required_data": ["pit_bars"],
                "benchmark_ids": ["always_flat"],
                "status": "FROZEN",
                "annotations": [
                    "reviewed external held-out research"
                ],
            }
        ],
        "datasets": [
            {
                "dataset_snapshot_id": "dataset:btc:heldout:v1",
                "created_at_utc": (
                    T0 - timedelta(days=2)
                ).isoformat(),
                "as_of_utc": (
                    T0 - timedelta(days=1)
                ).isoformat(),
                "start_at_utc": (
                    T0 - timedelta(days=90)
                ).isoformat(),
                "end_at_utc": (
                    T0 - timedelta(days=1)
                ).isoformat(),
                "asset_ids": ["btc"],
                "data_version": "btc-bars-reviewed-v1",
                "source_registry_version": "sources-reviewed-v1",
                "product_registry_version": "products-reviewed-v1",
                "calendar_version": "crypto-24x7-v1",
                "pit": True,
                "missing_data_policy": "fail_closed",
                "content_hash": HEX64,
            }
        ],
        "experiments": [
            {
                "experiment_id": (
                    "experiment:btc:daily_swing:long:v1"
                ),
                "hypothesis_id": (
                    "hyp:btc:daily_swing:long:v1"
                ),
                "parent_experiment_id": None,
                "created_at_utc": (
                    T0 - timedelta(days=2)
                ).isoformat(),
                "frozen_at_utc": (
                    T0 - timedelta(days=2)
                ).isoformat(),
                "research_state": "FROZEN",
                "parameter_spec": {"lookback": 20},
                "parameter_space_hash": "c" * 64,
                "dataset_snapshot_id": (
                    "dataset:btc:heldout:v1"
                ),
                "code_commit_sha": SHA40,
                "owner": "Research",
                "supersedes_experiment_id": None,
            }
        ],
        "runs": [
            {
                "backtest_run_id": (
                    "run:btc:daily_swing:long:v1"
                ),
                "experiment_id": (
                    "experiment:btc:daily_swing:long:v1"
                ),
                "run_type": "held_out",
                "dataset_snapshot_id": (
                    "dataset:btc:heldout:v1"
                ),
                "playbook_id": "pb_crypto_swing_v1_2",
                "playbook_version": "1.2",
                "code_commit_sha": SHA40,
                "cost_model_version": "cost-reviewed-v1",
                "execution_model_version": (
                    "execution-reviewed-v1"
                ),
                "random_seed": 7,
                "started_at_utc": (
                    T0 - timedelta(days=2)
                ).isoformat(),
                "finished_at_utc": (
                    T0 - timedelta(days=1, hours=12)
                ).isoformat(),
                "status": "COMPLETE",
                "integrity_flags": [],
                "metrics_json": {"n": 1},
            }
        ],
        "folds": [
            {
                "fold_result_id": (
                    "fold:btc:daily_swing:long:v1"
                ),
                "backtest_run_id": (
                    "run:btc:daily_swing:long:v1"
                ),
                "fold_index": 1,
                "train_start_utc": (
                    T0 - timedelta(days=90)
                ).isoformat(),
                "train_end_utc": (
                    T0 - timedelta(days=31)
                ).isoformat(),
                "test_start_utc": (
                    T0 - timedelta(days=30)
                ).isoformat(),
                "test_end_utc": (
                    T0 - timedelta(days=1)
                ).isoformat(),
                "n": 1,
                "net_pnl": -1.0,
                "expectancy_r": -0.1,
                "profit_factor": 0.0,
                "stop_rate": 1.0,
                "max_drawdown": 1.0,
                "cost_drag": 0.1,
                "benchmark_result": {
                    "benchmark_id": "always_flat"
                },
                "passed": False,
                "failure_reasons": [
                    "negative_net_edge"
                ],
            }
        ],
        "windows": [
            {
                "evidence_window_id": (
                    "heldout:btc:daily_swing:long:v1"
                ),
                "route_id": "btc:daily_swing:long",
                "playbook_id": "pb_crypto_swing_v1_2",
                "playbook_version": "1.2",
                "first_timestamp_utc": (
                    T0 - timedelta(days=20)
                ).isoformat(),
                "last_timestamp_utc": (
                    T0 - timedelta(days=10)
                ).isoformat(),
                "n": 1,
                "immutable_trade_ids": [
                    "research-trade:btc:1"
                ],
                "metrics_snapshot_hash": "d" * 64,
                "created_at_utc": (
                    T0 - timedelta(days=1)
                ).isoformat(),
                "backtest_run_id": (
                    "run:btc:daily_swing:long:v1"
                ),
                "fold_result_ids": [
                    "fold:btc:daily_swing:long:v1"
                ],
            }
        ],
    }


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        bootstrap_canonical_policy_snapshot(
            conn,
            store,
            effective_at_utc=T0 - timedelta(days=120),
            created_at_utc=T0 - timedelta(days=120),
        )
    return engine, store


def test_partial_real_manifest_persists_provenanced_window() -> None:
    manifest = parse_held_out_research_manifest(_payload())
    engine, store = _store()

    with engine.begin() as conn:
        report = persist_held_out_research_manifest(
            conn,
            store,
            manifest,
            require_canonical_universe=False,
        )
        provenance = conn.execute(
            sa.select(
                store.tables["held_out_evidence_provenance"]
            )
        ).mappings().one()

    assert report["persisted"] is True
    assert report["canonical_executable_route_count"] == 74
    assert report["supplied_route_count"] == 1
    assert report["missing_route_count"] == 73
    assert len(report["provenance_hashes"]) == 1
    assert (
        provenance["backtest_run_id"]
        == "run:btc:daily_swing:long:v1"
    )


def test_strict_import_refuses_partial_before_mutation() -> None:
    manifest = parse_held_out_research_manifest(_payload())
    engine, store = _store()

    with engine.begin() as conn:
        report = persist_held_out_research_manifest(
            conn,
            store,
            manifest,
            require_canonical_universe=True,
        )
        hypothesis_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["research_hypotheses"]
            )
        ).scalar_one()

    assert report["persisted"] is False
    assert report["missing_route_count"] == 73
    assert hypothesis_count == 0


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (
            ("datasets", 0, "content_hash"),
            "not-a-hash",
            "content_hash must be a lowercase 64-hex digest",
        ),
        (
            ("experiments", 0, "code_commit_sha"),
            "abc123",
            "code_commit_sha must be a lowercase 40-hex commit SHA",
        ),
        (
            ("windows", 0, "metrics_snapshot_hash"),
            "placeholder",
            (
                "metrics_snapshot_hash must be a lowercase "
                "64-hex digest"
            ),
        ),
    ),
)
def test_import_rejects_placeholder_provenance_identity(
    path: tuple[object, ...],
    value: object,
    message: str,
) -> None:
    payload = deepcopy(_payload())
    section, index, field = path
    payload[section][index][field] = value

    with pytest.raises(ValueError, match=message):
        parse_held_out_research_manifest(payload)
