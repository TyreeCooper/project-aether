from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import hashlib

from aether_vnext.evidence import ProfitabilityEvidence
from aether_vnext.exit_plan import EXIT_PRECEDENCE, ExitReason
from aether_vnext.identity import idempotency_key, position_key, route_id, signal_key
from aether_vnext.reason_codes import ReasonCode


UTC = timezone.utc
TS = datetime(2026, 9, 25, 19, 30, tzinfo=UTC)


def test_route_and_position_keys_use_frozen_format() -> None:
    assert route_id("EURUSD", "Intraday", "LONG") == "eurusd:intraday:long"
    assert position_key("EURUSD", "Intraday") == "eurusd:intraday"


def test_signal_key_uses_frozen_material_order() -> None:
    got = signal_key(
        setup_id="setup-1",
        asset_id="BTC",
        horizon="daily_swing",
        side="LONG",
        trigger_bar_close_exchange_ts=TS,
    )
    raw = "setup-1|btc|daily_swing|long|" + TS.isoformat()
    assert got == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_idempotency_key_changes_when_quantity_changes() -> None:
    one = idempotency_key(
        ticket_id="t1",
        side="long",
        qty=1.0,
        asset_id="mes",
        horizon="intraday",
        signal_key_value="sig",
    )
    two = idempotency_key(
        ticket_id="t1",
        side="long",
        qty=2.0,
        asset_id="mes",
        horizon="intraday",
        signal_key_value="sig",
    )
    assert one != two


def test_exit_precedence_matches_master_order() -> None:
    assert EXIT_PRECEDENCE == (
        ExitReason.GOVERNOR_HALT,
        ExitReason.HARD_STOP,
        ExitReason.STALE_MARK,
        ExitReason.SESSION_FLATTEN,
        ExitReason.STRUCTURE,
        ExitReason.TIME_STOP,
        ExitReason.TRAIL,
        ExitReason.PROFIT_TAKE,
    )


def test_minimum_reason_vocabulary_is_canonical() -> None:
    required = {
        "unsupported_product",
        "quote_stale",
        "lifecycle_ineligible",
        "no_setup",
        "grain_conflict",
        "session_closed",
        "route_benched",
        "forming_bar",
        "invalidation_hit",
        "no_completed_breakout",
        "bad_stop",
        "too_small",
        "asset_risk_full",
        "cluster_risk_full",
        "portfolio_risk_full",
        "insufficient_capital",
        "cost_hurdle_exceeds_expected_move",
        "signal_consumed",
        "duplicate_position_key",
        "broker_reject",
        "route_halted",
        "plan_complete",
        "side_not_supported",
        "product_side_unsupported",
        "market_changed",
        "market_stale",
        "bad_fill_through_stop",
    }
    assert required <= {x.value for x in ReasonCode}


def test_profitability_evidence_contains_master_part_iv_fields() -> None:
    names = {f.name for f in fields(ProfitabilityEvidence)}
    assert {
        "evidence_id",
        "route_id",
        "playbook_id",
        "playbook_version",
        "policy_version",
        "configuration_hash",
        "data_version",
        "fill_model_version",
        "fee_schedule_version",
        "in_sample_window",
        "oos_windows",
        "n_trades",
        "net_expectancy_usd",
        "profit_factor",
        "win_rate",
        "avg_win_usd",
        "avg_loss_usd",
        "stop_rate",
        "max_drawdown_usd",
        "max_drawdown_pct",
        "median_duration_s",
        "capture_efficiency",
        "cost_sensitivity",
        "regime_matrix",
        "benchmark_result",
        "capacity_result",
        "portfolio_contribution",
        "model_risks",
        "verdict",
        "reviewer",
        "as_of_utc",
    } <= names
