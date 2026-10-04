from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

from aether_vnext.store import canonical_payload_hash


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 22, 15, tzinfo=UTC)


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_restart_evidence_compare.py"
    )
    spec = importlib.util.spec_from_file_location("restart_evidence_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state_payload() -> dict[str, object]:
    return {
        "event_count": 10,
        "broker_ledgers": [
            {
                "broker_account_id": "kraken_paper",
                "cash_available_usd": 4000.0,
                "cash_reserved_usd": 0.0,
                "margin_used_usd": 0.0,
                "margin_available_usd": 4000.0,
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_usd": 0.0,
                "fees_accrued_usd": 0.0,
                "carry_accrued_usd": 0.0,
                "settled_cash_usd": 4000.0,
                "reconciliation_state": "clean",
                "row_version": 1,
            }
        ],
        "in_flight_setups": [],
        "in_flight_tickets": [],
        "in_flight_order_intents": [],
        "active_positions": [],
        "open_trade_records": [],
        "consumed_signals": [],
        "mutation_idempotency": [],
        "risk_admission_issues": [],
    }


def _snapshot_payload(
    *,
    snapshot_id: str,
    at: datetime,
    state: dict[str, object] | None = None,
) -> dict[str, object]:
    state_payload = deepcopy(state if state is not None else _state_payload())
    return {
        "snapshot_id": snapshot_id,
        "deployed_revision": "revision-1",
        "scenario": "open_trade",
        "observed_at_utc": at.isoformat(),
        "state_payload": state_payload,
        "state_payload_hash": canonical_payload_hash(state_payload),
        "reconciliation_blockers": [],
        "source_artifact_ids": [f"artifact-{snapshot_id}"],
        "synthetic": False,
    }


def test_cli_projection_emits_verified_canonical_restart_evidence() -> None:
    module = _load_script()
    result = module.compare_payloads(
        scenario_id="restart-open-1",
        before_payload=_snapshot_payload(snapshot_id="before", at=T0),
        after_payload=_snapshot_payload(
            snapshot_id="after",
            at=T0 + timedelta(seconds=5),
        ),
    )

    assert result["verified"] is True
    assert result["scenario"] == "open_trade"
    assert result["identity_preserved"] is True
    assert result["cash_preserved"] is True
    assert result["margin_preserved"] is True
    assert result["position_state_preserved"] is True
    assert result["idempotency_preserved"] is True
    assert result["reconciliation_clean"] is True
    assert result["comparator_authority"]["runtime_mutation"] is False
    assert result["comparator_authority"]["restart_authority"] is False


def test_cli_projection_surfaces_drift_without_claiming_verified() -> None:
    module = _load_script()
    after_state = _state_payload()
    after_state["event_count"] = 11

    result = module.compare_payloads(
        scenario_id="restart-open-drift",
        before_payload=_snapshot_payload(snapshot_id="before", at=T0),
        after_payload=_snapshot_payload(
            snapshot_id="after",
            at=T0 + timedelta(seconds=5),
            state=after_state,
        ),
    )

    assert result["verified"] is False
    assert result["event_count_preserved"] is False
    assert result["identity_preserved"] is False
