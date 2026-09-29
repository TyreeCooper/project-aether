"""Emit a read-only Phase-17 restart evidence snapshot from burn-in."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.restart_evidence_snapshot import (
    RESTART_EVIDENCE_SCENARIOS,
    collect_restart_evidence_snapshot,
)
from aether_vnext.store import VNextStore


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    snapshot_id: str,
    deployed_revision: str,
    scenario: str,
    source_artifact_id: str,
    output: str | None,
) -> int:
    store = VNextStore(schema="aether_vnext")
    observed_at_utc = datetime.now(timezone.utc)

    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            snapshot = await connection.run_sync(
                lambda conn: collect_restart_evidence_snapshot(
                    conn,
                    store=store,
                    snapshot_id=snapshot_id,
                    deployed_revision=deployed_revision,
                    scenario=scenario,
                    observed_at_utc=observed_at_utc,
                    source_artifact_ids=(source_artifact_id,),
                )
            )

    payload: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "deployed_revision": snapshot.deployed_revision,
        "scenario": snapshot.scenario,
        "observed_at_utc": snapshot.observed_at_utc.isoformat(),
        "state_payload": snapshot.state_payload,
        "state_payload_hash": snapshot.state_payload_hash,
        "reconciliation_blockers": list(snapshot.reconciliation_blockers),
        "source_artifact_ids": list(snapshot.source_artifact_ids),
        "synthetic": False,
        "collector_authority": {
            "read_only": True,
            "may_reconcile": False,
            "may_reseed_cash": False,
            "may_cancel_intents": False,
            "may_restart_runtime": False,
            "live_execution_authorized": False,
        },
    }
    _emit(payload, output)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--deployed-revision", required=True)
    parser.add_argument(
        "--scenario",
        required=True,
        choices=tuple(sorted(RESTART_EVIDENCE_SCENARIOS)),
    )
    parser.add_argument("--source-artifact-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                snapshot_id=args.snapshot_id,
                deployed_revision=args.deployed_revision,
                scenario=args.scenario,
                source_artifact_id=args.source_artifact_id,
                output=args.output,
            )
        )
    )
