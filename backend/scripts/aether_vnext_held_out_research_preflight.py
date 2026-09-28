"""Read-only preflight for the canonical vNext HELD_OUT replay plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aether_vnext.held_out_research_runner import (
    parse_held_out_replay_input,
    preflight_canonical_held_out_research_runner,
)


def _load_plan(
    *,
    plan_json: str | None,
    plan_file: str | None,
):
    if plan_json is None and plan_file is None:
        return None
    if plan_json is not None and plan_file is not None:
        raise ValueError("choose at most one of --plan-json or --plan-file")
    raw = (
        plan_json
        if plan_json is not None
        else Path(str(plan_file)).read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("replay plan must be a JSON object")
    return parse_held_out_replay_input(payload)


def main(
    *,
    plan_json: str | None = None,
    plan_file: str | None = None,
) -> int:
    input_ = _load_plan(
        plan_json=plan_json,
        plan_file=plan_file,
    )
    result = preflight_canonical_held_out_research_runner(input_)
    print(
        json.dumps(
            {
                "startable": result.startable,
                "route_count": result.route_count,
                "required_indicators": list(result.required_indicators),
                "required_asset_ids": list(result.required_asset_ids),
                "dataset_snapshot_id": result.dataset_snapshot_id,
                "fold_count": result.fold_count,
                "work_item_count": result.work_item_count,
                "blockers": list(result.blockers),
                "routes": [
                    {
                        "route_id": row.route_id,
                        "playbook_id": row.playbook_id,
                        "playbook_version": row.playbook_version,
                        "mechanism_class": row.mechanism_class,
                    }
                    for row in result.routes
                ],
                "work_items": [
                    {
                        "work_item_id": row.work_item_id,
                        "route_id": row.route_id,
                        "playbook_id": row.playbook_id,
                        "playbook_version": row.playbook_version,
                        "dataset_snapshot_id": row.dataset_snapshot_id,
                        "dataset_content_hash": row.dataset_content_hash,
                        "fold_index": row.fold_index,
                        "test_start_utc": row.test_start_utc.isoformat(),
                        "test_end_utc": row.test_end_utc.isoformat(),
                        "code_commit_sha": row.code_commit_sha,
                        "configuration_hash": row.configuration_hash,
                    }
                    for row in result.work_items
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.startable else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--plan-json")
    source.add_argument("--plan-file")
    args = parser.parse_args()
    raise SystemExit(
        main(
            plan_json=args.plan_json,
            plan_file=args.plan_file,
        )
    )
