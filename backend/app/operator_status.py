"""Operator-facing strategy status and read-only live-readiness map.

This module exposes evidence state without enabling Kraken live execution.
"""
from __future__ import annotations

from typing import Any

from app.agreement import strategy_agreement


LIVE_READINESS = {
    "execution_adapter_boundary": "gap",
    "idempotent_order_model": "gap",
    "client_order_ids": "gap",
    "partial_fills": "gap",
    "cancel_reject_handling": "gap",
    "private_ws_reconciliation": "gap",
    "rest_fallback": "gap",
    "account_position_balance_reconciliation": "gap",
    "fee_tier_configuration": "gap",
    "nonce_rate_limit_retry": "gap",
    "credential_isolation_rotation": "partial",
    "startup_recovery": "partial",
    "stale_data_clock_handling": "partial",
    "kill_switch_flatten": "partial",
    "max_loss_max_position": "partial",
    "audit_trail": "partial",
    "dry_run_canary": "gap",
    "sandbox_staging": "gap",
    "observability_alerts": "partial",
    "operator_approval_gate": "partial",
}


def operator_strategy_status(
    held_out: dict[str, Any],
    forward: dict[str, Any],
) -> dict[str, Any]:
    agreement = strategy_agreement(held_out, forward)
    return {
        "strategy": {
            "agreement": agreement,
            "agree_done": bool(agreement["agreement"]),
        },
        "execution": {
            "mode": "paper",
            "live_blocked": True,
            "kraken_live_orders_enabled": False,
        },
        "live_readiness": {
            "read_only": True,
            "items": dict(LIVE_READINESS),
        },
    }
