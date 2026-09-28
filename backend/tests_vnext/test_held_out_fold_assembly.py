from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

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


def _fold() -> HeldOutFoldPlan:
    return HeldOutFoldPlan(
        fold_index=2,
        train_start_utc=T0,
        train_end_utc=T0 + timedelta(days=59),
        test_start_utc=T0 + timedelta(days=60),
        test_end_utc=T0 + timedelta(days=89),
    )


def _work() -> HeldOutReplayWorkItem:
    fold = _fold()
    return HeldOutReplayWorkItem(
        work_item_id="work-2",
        route_id="nvda:intraday:long",
        playbook_id="pb_eq_intraday_v1_2",
        playbook_version="1.2",
        mechanism_class="breakout_continuation",
        dataset_snapshot_id="dataset-1",
        dataset_content_hash="a" * 64,
        fold_index=fold.fold_index,
        test_start_utc=fold.test_start_utc,
        test_end_utc=fold.test_end_utc,
        code_commit_sha="b" * 40,
        configuration_hash="c" * 64,
    )


def _trade(
    trade_id: str,
    *,
    day: int,
    gross: float,
    cost: float,
    net_r: float,
    stopped: bool = False,
) -> ReplayTradeOutcome:
    opened = T0 + timedelta(days=day, hours=1)
    return ReplayTradeOutcome(
        trade_id=trade_id,
        opened_at_utc=opened,
        closed_at_utc=opened + timedelta(minutes=90),
        gross_pnl_usd=gross,
        base_cost_usd=cost,
        net_r=net_r,
        stopped=stopped,
        capture_efficiency=0.5,
    )


def test_fold_assembly_reuses_existing_profitability_metrics() -> None:
    trades = (
        _trade("trade-1", day=61, gross=10.0, cost=2.0, net_r=1.0),
        _trade(
            "trade-2",
            day=62,
            gross=-4.0,
            cost=1.0,
            net_r=-0.5,
            stopped=True,
        ),
    )
    out = assemble_held_out_fold(
        _work(),
        _fold(),
        backtest_run_id="run-1",
        trades=trades,
        replay_status=ReplayResultStatus.COMPLETE,
        benchmark_result={"benchmark_id": "always_flat"},
        passed=True,
    )

    assert out.fold_result.n == 2
    assert out.fold_result.net_pnl == pytest.approx(3.0)
    assert out.fold_result.expectancy_r == pytest.approx(0.25)
    assert out.fold_result.profit_factor == pytest.approx(8.0 / 5.0)
    assert out.fold_result.stop_rate == pytest.approx(0.5)
    assert out.fold_result.cost_drag == pytest.approx(3.0)
    assert out.fold_result.max_drawdown == pytest.approx(5.0)
    assert out.fold_result.benchmark_result == {
        "benchmark_id": "always_flat"
    }
    assert out.replay_result.immutable_trade_ids == (
        "trade-1",
        "trade-2",
    )
    assert out.replay_result.status is ReplayResultStatus.COMPLETE


def test_all_winner_fold_preserves_infinite_profit_factor() -> None:
    out = assemble_held_out_fold(
        _work(),
        _fold(),
        backtest_run_id="run-1",
        trades=(
            _trade("winner", day=61, gross=5.0, cost=1.0, net_r=0.4),
        ),
        replay_status=ReplayResultStatus.COMPLETE,
        benchmark_result={},
        passed=True,
    )
    assert math.isinf(out.fold_result.profit_factor)


def test_zero_trade_fold_is_recordable_without_fabricating_trades() -> None:
    out = assemble_held_out_fold(
        _work(),
        _fold(),
        backtest_run_id="run-1",
        trades=(),
        replay_status=ReplayResultStatus.FAILED_EVIDENCE,
        benchmark_result={},
        passed=False,
        failure_reasons=("no_trades",),
    )
    assert out.fold_result.n == 0
    assert out.fold_result.net_pnl == 0.0
    assert out.fold_result.expectancy_r == 0.0
    assert out.immutable_trade_ids == ()


def test_trade_must_be_fully_inside_held_out_test_window() -> None:
    work = _work()
    fold = _fold()
    early = ReplayTradeOutcome(
        trade_id="early",
        opened_at_utc=fold.test_start_utc - timedelta(seconds=1),
        closed_at_utc=fold.test_start_utc + timedelta(minutes=1),
        gross_pnl_usd=1.0,
        base_cost_usd=0.1,
        net_r=0.1,
    )
    with pytest.raises(ValueError, match="opens before"):
        assemble_held_out_fold(
            work,
            fold,
            backtest_run_id="run-1",
            trades=(early,),
            replay_status=ReplayResultStatus.COMPLETE,
            benchmark_result={},
            passed=True,
        )

    late = ReplayTradeOutcome(
        trade_id="late",
        opened_at_utc=fold.test_end_utc - timedelta(minutes=1),
        closed_at_utc=fold.test_end_utc + timedelta(seconds=1),
        gross_pnl_usd=1.0,
        base_cost_usd=0.1,
        net_r=0.1,
    )
    with pytest.raises(ValueError, match="closes after"):
        assemble_held_out_fold(
            work,
            fold,
            backtest_run_id="run-1",
            trades=(late,),
            replay_status=ReplayResultStatus.COMPLETE,
            benchmark_result={},
            passed=True,
        )


def test_fold_geometry_must_match_replay_work_item() -> None:
    fold = _fold()
    mismatched = HeldOutFoldPlan(
        fold_index=fold.fold_index,
        train_start_utc=fold.train_start_utc,
        train_end_utc=fold.train_end_utc,
        test_start_utc=fold.test_start_utc + timedelta(days=1),
        test_end_utc=fold.test_end_utc,
    )
    with pytest.raises(ValueError, match="test_start"):
        assemble_held_out_fold(
            _work(),
            mismatched,
            backtest_run_id="run-1",
            trades=(),
            replay_status=ReplayResultStatus.FAILED_EVIDENCE,
            benchmark_result={},
            passed=False,
        )


def test_fold_verdict_and_failure_reasons_remain_explicit() -> None:
    with pytest.raises(ValueError, match="passed fold"):
        assemble_held_out_fold(
            _work(),
            _fold(),
            backtest_run_id="run-1",
            trades=(),
            replay_status=ReplayResultStatus.COMPLETE,
            benchmark_result={},
            passed=True,
            failure_reasons=("should_not_exist",),
        )


def test_trade_outcome_rejects_nonfinite_r_and_reversed_time() -> None:
    opened = _fold().test_start_utc + timedelta(days=1)
    with pytest.raises(ValueError, match="net_r"):
        ReplayTradeOutcome(
            trade_id="bad-r",
            opened_at_utc=opened,
            closed_at_utc=opened + timedelta(minutes=1),
            gross_pnl_usd=1.0,
            base_cost_usd=0.0,
            net_r=math.nan,
        )
    with pytest.raises(ValueError, match="cannot precede"):
        ReplayTradeOutcome(
            trade_id="backward",
            opened_at_utc=opened,
            closed_at_utc=opened - timedelta(minutes=1),
            gross_pnl_usd=1.0,
            base_cost_usd=0.0,
            net_r=0.1,
        )
