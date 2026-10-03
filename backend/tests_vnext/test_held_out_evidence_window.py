from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.evidence import SampleDomain
from aether_vnext.held_out_evidence_window import (
    assemble_held_out_evidence_window,
    held_out_metrics_snapshot_hash,
)
from aether_vnext.held_out_fold_assembly import (
    ReplayTradeOutcome,
    assemble_held_out_fold,
)
from aether_vnext.held_out_replay_results import ReplayResultStatus
from aether_vnext.held_out_research_runner import (
    HeldOutFoldPlan,
    HeldOutReplayWorkItem,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _fold(index: int) -> HeldOutFoldPlan:
    start_day = index * 30
    return HeldOutFoldPlan(
        fold_index=index,
        train_start_utc=T0,
        train_end_utc=T0 + timedelta(days=start_day + 19),
        test_start_utc=T0 + timedelta(days=start_day + 20),
        test_end_utc=T0 + timedelta(days=start_day + 29),
    )


def _work(index: int, *, route_id: str = "nvda:intraday:long") -> HeldOutReplayWorkItem:
    fold = _fold(index)
    return HeldOutReplayWorkItem(
        work_item_id=f"work-{index}",
        route_id=route_id,
        playbook_id="pb_eq_intraday_v1_2",
        playbook_version="1.2",
        mechanism_class="breakout_continuation",
        dataset_snapshot_id="dataset-1",
        dataset_content_hash="a" * 64,
        fold_index=index,
        test_start_utc=fold.test_start_utc,
        test_end_utc=fold.test_end_utc,
        code_commit_sha="b" * 40,
        configuration_hash="c" * 64,
    )


def _trade(index: int, trade_id: str) -> ReplayTradeOutcome:
    fold = _fold(index)
    opened = fold.test_start_utc + timedelta(days=1)
    return ReplayTradeOutcome(
        trade_id=trade_id,
        opened_at_utc=opened,
        closed_at_utc=opened + timedelta(hours=1),
        gross_pnl_usd=10.0 + index,
        base_cost_usd=1.0,
        net_r=0.5 + index * 0.1,
        stopped=False,
        capture_efficiency=0.4,
    )


def _assembly(
    index: int,
    trade_id: str,
    *,
    route_id: str = "nvda:intraday:long",
):
    return assemble_held_out_fold(
        _work(index, route_id=route_id),
        _fold(index),
        backtest_run_id="run-1",
        trades=(_trade(index, trade_id),),
        replay_status=ReplayResultStatus.COMPLETE,
        benchmark_result={"benchmark_id": "always_flat"},
        passed=True,
    )


def test_evidence_window_aggregates_nonoverlapping_folds_deterministically() -> None:
    first = _assembly(0, "trade-1")
    second = _assembly(1, "trade-2")
    created = _fold(1).test_end_utc + timedelta(seconds=1)

    out = assemble_held_out_evidence_window(
        (second, first),
        policy_version="policy-v1",
        configuration_hash="c" * 64,
        created_at_utc=created,
    )

    assert out.window.sample_domain is SampleDomain.HELD_OUT
    assert out.window.route_id == "nvda:intraday:long"
    assert out.window.playbook_id == "pb_eq_intraday_v1_2"
    assert out.window.n == 2
    assert out.window.immutable_trade_ids == ("trade-1", "trade-2")
    assert out.fold_result_ids == (
        first.fold_result.fold_result_id,
        second.fold_result.fold_result_id,
    )
    assert out.window.first_timestamp_utc == _fold(0).test_start_utc
    assert out.window.last_timestamp_utc == _fold(1).test_end_utc

    again = assemble_held_out_evidence_window(
        (first, second),
        policy_version="policy-v1",
        configuration_hash="c" * 64,
        created_at_utc=created,
    )
    assert again.window.evidence_window_id == out.window.evidence_window_id
    assert again.window.metrics_snapshot_hash == out.window.metrics_snapshot_hash
    assert held_out_metrics_snapshot_hash((second, first)) == (
        held_out_metrics_snapshot_hash((first, second))
    )


def test_duplicate_trade_across_folds_fails_closed() -> None:
    first = _assembly(0, "shared-trade")
    second = _assembly(1, "shared-trade")
    with pytest.raises(ValueError, match="multiple held-out folds"):
        assemble_held_out_evidence_window(
            (first, second),
            policy_version="policy-v1",
            configuration_hash="c" * 64,
            created_at_utc=_fold(1).test_end_utc + timedelta(seconds=1),
        )


def test_route_family_mismatch_fails_closed() -> None:
    first = _assembly(0, "trade-1")
    second = _assembly(
        1,
        "trade-2",
        route_id="nvda:intraday:short",
    )
    with pytest.raises(ValueError, match="route_id"):
        assemble_held_out_evidence_window(
            (first, second),
            policy_version="policy-v1",
            configuration_hash="c" * 64,
            created_at_utc=_fold(1).test_end_utc + timedelta(seconds=1),
        )


def test_zero_trade_folds_cannot_create_positive_evidence_window() -> None:
    fold = _fold(0)
    empty = assemble_held_out_fold(
        _work(0),
        fold,
        backtest_run_id="run-1",
        trades=(),
        replay_status=ReplayResultStatus.FAILED_EVIDENCE,
        benchmark_result={},
        passed=False,
        failure_reasons=("no_trades",),
    )
    with pytest.raises(ValueError, match="at least one immutable trade"):
        assemble_held_out_evidence_window(
            (empty,),
            policy_version="policy-v1",
            configuration_hash="c" * 64,
            created_at_utc=fold.test_end_utc + timedelta(seconds=1),
        )


def test_created_at_cannot_predate_window_end() -> None:
    first = _assembly(0, "trade-1")
    with pytest.raises(ValueError, match="cannot precede"):
        assemble_held_out_evidence_window(
            (first,),
            policy_version="policy-v1",
            configuration_hash="c" * 64,
            created_at_utc=_fold(0).test_end_utc - timedelta(seconds=1),
        )
