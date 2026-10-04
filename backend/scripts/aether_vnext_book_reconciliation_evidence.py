"""Emit read-only Phase-17 book reconciliation evidence from burn-in."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.book_reconciliation_evidence import (
    collect_book_reconciliation_evidence,
)
from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.store import VNextStore


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    evidence_id: str,
    deployed_revision: str,
    source_artifact_id: str,
    output: str | None,
) -> int:
    store = VNextStore(schema="aether_vnext")
    observed_at_utc = datetime.now(timezone.utc)

    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            collected = await connection.run_sync(
                lambda conn: collect_book_reconciliation_evidence(
                    conn,
                    store=store,
                    evidence_id=evidence_id,
                    deployed_revision=deployed_revision,
                    observed_at_utc=observed_at_utc,
                    source_artifact_ids=(source_artifact_id,),
                )
            )

    evidence = collected.evidence
    payload: dict[str, object] = {
        "evidence_id": evidence.evidence_id,
        "deployed_revision": evidence.deployed_revision,
        "observed_at_utc": evidence.observed_at_utc.isoformat(),
        "risk_admission_issues": list(evidence.risk_admission_issues),
        "stale_order_intent_ids": list(evidence.stale_order_intent_ids),
        "active_position_trade_identity_consistent": (
            evidence.active_position_trade_identity_consistent
        ),
        "active_position_identity_issues": list(
            collected.active_position_identity_issues
        ),
        "broker_ledger_balanced": evidence.broker_ledger_balanced,
        "broker_ledger_issues": list(collected.broker_ledger_issues),
        "source_artifact_ids": list(evidence.source_artifact_ids),
        "synthetic": False,
        "verified": evidence.verified,
        "collector_authority": {
            "read_only": True,
            "may_repair_book": False,
            "may_cancel_intents": False,
            "may_reseed_cash": False,
            "may_switch_runtime": False,
            "live_execution_authorized": False,
        },
    }
    _emit(payload, output)
    return 0 if evidence.verified else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--deployed-revision", required=True)
    parser.add_argument("--source-artifact-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                evidence_id=args.evidence_id,
                deployed_revision=args.deployed_revision,
                source_artifact_id=args.source_artifact_id,
                output=args.output,
            )
        )
    )
