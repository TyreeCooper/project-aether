"""Start a clean AETHER vNext paper-test epoch.

Default behavior is read-only preview. Execution requires BOTH --execute and the
exact confirmation token. The command operates only through the isolated vNext
burn-in database configuration enforced by db_runtime.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.store import VNextStore


CONFIRM_TOKEN = "RESET-VNEXT-PAPER-TEST"


def preview_payload(preview: dict[str, object]) -> dict[str, object]:
    return {
        "mode": "preview",
        "resettable": bool(preview["resettable"]),
        "blockers": list(preview["blockers"]),
        "seed_sleeves": dict(preview["seed_sleeves"]),
        "seed_bank_total_usd": float(preview["seed_bank_total_usd"]),
        "prior_state_hash": str(preview["prior_state_hash"]),
        "prior_state": preview["prior_state"],
        "paper_only": True,
        "live_blocked": True,
        "mutation_performed": False,
    }


def require_execute_confirmation(*, execute: bool, confirm: str | None) -> None:
    if not execute:
        return
    if confirm != CONFIRM_TOKEN:
        raise ValueError(
            f"--execute requires --confirm {CONFIRM_TOKEN}"
        )


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    epoch_id: str,
    reason: str,
    execute: bool,
    confirm: str | None,
    output: str | None,
) -> int:
    require_execute_confirmation(execute=execute, confirm=confirm)
    store = VNextStore(schema="aether_vnext")

    async with open_vnext_engine() as engine:
        if not execute:
            async with engine.connect() as connection:
                preview = await connection.run_sync(
                    store.paper_test_reset_preview
                )
            payload = preview_payload(preview)
            _emit(payload, output)
            return 0 if payload["resettable"] else 2

        started_at = datetime.now(timezone.utc)
        async with engine.begin() as connection:
            preview = await connection.run_sync(
                store.paper_test_reset_preview
            )
            if not preview["resettable"]:
                payload = preview_payload(preview)
                payload["mode"] = "blocked"
                _emit(payload, output)
                return 2

            epoch = await connection.run_sync(
                lambda conn: store.start_new_paper_test_epoch(
                    conn,
                    epoch_id=epoch_id,
                    started_at_utc=started_at,
                    reason=reason,
                    created_at_utc=started_at,
                )
            )
            ledgers = await connection.run_sync(store.ledger_rows)

        payload = {
            "mode": "executed",
            "resettable": True,
            "blockers": [],
            "epoch": epoch,
            "seed_bank_total_usd": float(epoch["seed_bank_total_usd"]),
            "current_ledgers": ledgers,
            "prior_state_hash": str(epoch["prior_state_hash"]),
            "paper_only": True,
            "live_blocked": True,
            "mutation_performed": True,
        }
        _emit(payload, output)
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epoch-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                epoch_id=args.epoch_id,
                reason=args.reason,
                execute=args.execute,
                confirm=args.confirm,
                output=args.output,
            )
        )
    )
