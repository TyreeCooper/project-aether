"""Read-only Phase 18 HELD_OUT closeout audit for AETHER vNext.

This command validates three reviewed artifacts entirely in memory:
- canonical HELD_OUT research manifest;
- deterministic HELD_OUT replay plan input;
- reviewed replay-result records.

It never opens the database, persists research, mutates evidence, calls providers,
or starts a campaign.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

from aether_vnext.held_out_closeout import (
    HeldOutCloseoutReadiness,
    build_held_out_closeout_readiness,
)
from aether_vnext.held_out_import import (
    parse_held_out_research_manifest,
    validate_held_out_research_manifest,
)
from aether_vnext.held_out_replay_results import (
    HeldOutReplayResultRecord,
    ReplayCoverageReport,
    ReplayResultStatus,
    validate_replay_result_coverage,
)
from aether_vnext.held_out_research_runner import (
    parse_held_out_replay_input,
    preflight_canonical_held_out_research_runner,
)


def _load_json_source(
    *,
    inline_json: str | None,
    file_path: str | None,
    label: str,
) -> object:
    if (inline_json is None) == (file_path is None):
        raise ValueError(
            f"choose exactly one {label} JSON source"
        )
    raw = (
        inline_json
        if inline_json is not None
        else Path(str(file_path)).read_text(encoding="utf-8")
    )
    return json.loads(raw)


def _canonical_text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    rows = tuple(_canonical_text(item, name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} cannot contain duplicates")
    return rows


def _parse_replay_results(payload: object) -> tuple[HeldOutReplayResultRecord, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("replay results payload must be a JSON object")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("results must be a list")

    out: list[HeldOutReplayResultRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("replay result entries must be JSON objects")
        raw_index = row.get("fold_index")
        if isinstance(raw_index, bool):
            raise ValueError("fold_index must be an integer")
        try:
            fold_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("fold_index must be an integer") from exc

        out.append(
            HeldOutReplayResultRecord(
                work_item_id=_canonical_text(
                    row.get("work_item_id"),
                    "work_item_id",
                ),
                route_id=_canonical_text(
                    row.get("route_id"),
                    "route_id",
                ),
                playbook_id=_canonical_text(
                    row.get("playbook_id"),
                    "playbook_id",
                ),
                playbook_version=_canonical_text(
                    row.get("playbook_version"),
                    "playbook_version",
                ),
                fold_index=fold_index,
                status=ReplayResultStatus(
                    _canonical_text(row.get("status"), "status")
                ),
                immutable_trade_ids=_strings(
                    row.get("immutable_trade_ids"),
                    "immutable_trade_ids",
                ),
                result_hash=_canonical_text(
                    row.get("result_hash"),
                    "result_hash",
                ),
            )
        )
    return tuple(out)


def _readiness_payload(
    readiness: HeldOutCloseoutReadiness,
    *,
    coverage: ReplayCoverageReport,
    replay_plan_startable: bool,
    replay_plan_blockers: tuple[str, ...],
) -> dict[str, object]:
    return {
        "ready": readiness.ready,
        "replay_plan_startable": replay_plan_startable,
        "replay_plan_blockers": list(replay_plan_blockers),
        "canonical_universe_complete": (
            readiness.canonical_universe_complete
        ),
        "replay_result_coverage_complete": (
            readiness.replay_result_coverage_complete
        ),
        "canonical_executable_route_count": (
            readiness.canonical_executable_route_count
        ),
        "supplied_route_count": readiness.supplied_route_count,
        "missing_route_count": readiness.missing_route_count,
        "expected_work_item_count": readiness.expected_work_item_count,
        "supplied_result_count": readiness.supplied_result_count,
        "fold_count": readiness.fold_count,
        "window_count": readiness.window_count,
        "blocker_counts": {
            code: count for code, count in readiness.blocker_counts
        },
        "missing_work_item_ids": list(
            coverage.missing_work_item_ids
        ),
        "unexpected_work_item_ids": list(
            coverage.unexpected_work_item_ids
        ),
        "duplicate_trade_ids": list(
            coverage.duplicate_trade_ids
        ),
    }


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


def main(
    *,
    manifest_json: str | None,
    manifest_file: str | None,
    plan_json: str | None,
    plan_file: str | None,
    results_json: str | None,
    results_file: str | None,
    extra_blockers: tuple[str, ...] = (),
    output: str | None = None,
) -> int:
    manifest_payload = _load_json_source(
        inline_json=manifest_json,
        file_path=manifest_file,
        label="manifest",
    )
    if not isinstance(manifest_payload, Mapping):
        raise ValueError("manifest must be a JSON object")
    manifest = parse_held_out_research_manifest(manifest_payload)
    manifest_report = validate_held_out_research_manifest(manifest)

    plan_payload = _load_json_source(
        inline_json=plan_json,
        file_path=plan_file,
        label="plan",
    )
    if not isinstance(plan_payload, Mapping):
        raise ValueError("replay plan must be a JSON object")
    replay_input = parse_held_out_replay_input(plan_payload)
    preflight = preflight_canonical_held_out_research_runner(
        replay_input
    )

    results_payload = _load_json_source(
        inline_json=results_json,
        file_path=results_file,
        label="results",
    )
    results = _parse_replay_results(results_payload)

    if not preflight.startable:
        payload = {
            "ready": False,
            "replay_plan_startable": False,
            "replay_plan_blockers": list(preflight.blockers),
            "supplied_result_count": len(results),
            "manifest_validation_report": manifest_report,
        }
        _emit(payload, output)
        return 2

    coverage = validate_replay_result_coverage(
        preflight,
        results,
    )
    readiness = build_held_out_closeout_readiness(
        manifest_validation_report=manifest_report,
        replay_coverage=coverage,
        extra_blockers=extra_blockers,
    )
    payload = _readiness_payload(
        readiness,
        coverage=coverage,
        replay_plan_startable=True,
        replay_plan_blockers=(),
    )
    _emit(payload, output)
    return 0 if readiness.ready else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    manifest = parser.add_mutually_exclusive_group(required=True)
    manifest.add_argument("--manifest-json")
    manifest.add_argument("--manifest-file")

    plan = parser.add_mutually_exclusive_group(required=True)
    plan.add_argument("--plan-json")
    plan.add_argument("--plan-file")

    results = parser.add_mutually_exclusive_group(required=True)
    results.add_argument("--results-json")
    results.add_argument("--results-file")

    parser.add_argument(
        "--extra-blocker",
        action="append",
        default=[],
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    raise SystemExit(
        main(
            manifest_json=args.manifest_json,
            manifest_file=args.manifest_file,
            plan_json=args.plan_json,
            plan_file=args.plan_file,
            results_json=args.results_json,
            results_file=args.results_file,
            extra_blockers=tuple(args.extra_blocker),
            output=args.output,
        )
    )
