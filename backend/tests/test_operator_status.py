from app.operator_status import LIVE_READINESS, operator_strategy_status


def test_operator_status_keeps_live_execution_blocked():
    held = {"ok": True, "profitability_gate_pass": True, "config": {"id": "v1"}}
    forward = {
        "ok": True,
        "profitability_gate_pass": True,
        "sample_gate_defined": True,
        "sample_gate_pass": True,
        "forward_gate_pass": True,
    }
    out = operator_strategy_status(held, forward)
    assert out["strategy"]["agree_done"] is True
    assert out["execution"]["mode"] == "paper"
    assert out["execution"]["live_blocked"] is True
    assert out["execution"]["kraken_live_orders_enabled"] is False


def test_operator_status_does_not_claim_agreement_without_forward_sample():
    held = {"ok": True, "profitability_gate_pass": True, "config": {"id": "v1"}}
    forward = {
        "ok": True,
        "profitability_gate_pass": True,
        "sample_gate_defined": False,
        "sample_gate_pass": False,
        "forward_gate_pass": False,
    }
    out = operator_strategy_status(held, forward)
    assert out["strategy"]["agree_done"] is False
    assert "forward_meaningful_sample_threshold" in out["strategy"]["agreement"]["blockers"]


def test_live_readiness_map_covers_critical_kraken_boundaries():
    required = {
        "execution_adapter_boundary", "idempotent_order_model", "client_order_ids",
        "partial_fills", "cancel_reject_handling", "private_ws_reconciliation",
        "rest_fallback", "account_position_balance_reconciliation",
        "fee_tier_configuration", "nonce_rate_limit_retry",
        "credential_isolation_rotation", "startup_recovery",
        "stale_data_clock_handling", "kill_switch_flatten",
        "max_loss_max_position", "audit_trail", "dry_run_canary",
        "sandbox_staging", "observability_alerts", "operator_approval_gate",
    }
    assert required <= set(LIVE_READINESS)
