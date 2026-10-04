from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aether_vnext.held_out_closeout import HeldOutCloseoutReadiness
from aether_vnext.held_out_replay_results import ReplayCoverageReport


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_held_out_closeout.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_held_out_closeout_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_result_parser_preserves_reviewed_identity() -> None:
    module = _module()
    rows = module._parse_replay_results(
        {
            "results": [
                {
                    "work_item_id": "work-1",
                    "route_id": "nvda:intraday:long",
                    "playbook_id": "pb_eq_intraday_v1_2",
                    "playbook_version": "1.2",
                    "fold_index": 3,
                    "status": "COMPLETE",
                    "immutable_trade_ids": [
                        "trade-1",
                        "trade-2",
                    ],
                    "result_hash": "a" * 64,
                }
            ]
        }
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.work_item_id == "work-1"
    assert row.fold_index == 3
    assert row.status.value == "COMPLETE"
    assert row.immutable_trade_ids == ("trade-1", "trade-2")


def test_replay_result_parser_rejects_duplicate_trade_ids() -> None:
    module = _module()
    with pytest.raises(ValueError, match="cannot contain duplicates"):
        module._parse_replay_results(
            {
                "results": [
                    {
                        "work_item_id": "work-1",
                        "route_id": "nvda:intraday:long",
                        "playbook_id": "pb_eq_intraday_v1_2",
                        "playbook_version": "1.2",
                        "fold_index": 0,
                        "status": "COMPLETE",
                        "immutable_trade_ids": [
                            "trade-1",
                            "trade-1",
                        ],
                        "result_hash": "a" * 64,
                    }
                ]
            }
        )


def test_readiness_payload_is_operator_stable() -> None:
    module = _module()
    readiness = HeldOutCloseoutReadiness(
        ready=False,
        canonical_universe_complete=False,
        replay_result_coverage_complete=False,
        canonical_executable_route_count=74,
        supplied_route_count=70,
        missing_route_count=4,
        expected_work_item_count=148,
        supplied_result_count=147,
        fold_count=140,
        window_count=70,
        blocker_counts=(
            ("held_out_manifest_missing_routes", 1),
            ("held_out_replay_results_incomplete", 1),
        ),
    )
    coverage = ReplayCoverageReport(
        expected_work_item_count=148,
        supplied_result_count=147,
        missing_work_item_ids=("work-148",),
        unexpected_work_item_ids=(),
        duplicate_trade_ids=(),
    )

    payload = module._readiness_payload(
        readiness,
        coverage=coverage,
        replay_plan_startable=True,
        replay_plan_blockers=(),
    )

    assert payload["ready"] is False
    assert payload["missing_route_count"] == 4
    assert payload["missing_work_item_ids"] == ["work-148"]
    assert payload["blocker_counts"] == {
        "held_out_manifest_missing_routes": 1,
        "held_out_replay_results_incomplete": 1,
    }


def test_emit_writes_exact_json(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "closeout.json"
    payload = {
        "ready": False,
        "blocker_counts": {
            "runtime_product_binding_missing": 1,
        },
    }

    module._emit(payload, str(output))

    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_closeout_cli_is_strictly_read_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "open_vnext_engine" not in source
    assert "VNextStore" not in source
    assert "persist_held_out_research_manifest" not in source
    assert "start_campaign" not in source
    assert "requests." not in source
    assert "httpx." not in source
