from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.held_out_replay_results import (
    ReplayResultStatus,
    bind_replay_result,
    require_complete_replay_result_coverage,
    validate_replay_result_coverage,
)
from aether_vnext.held_out_research_runner import (
    HeldOutResearchRunnerPreflight,
    HeldOutReplayWorkItem,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)


def _work(
    work_item_id: str,
    *,
    route_id: str,
    playbook_id: str,
    fold_index: int,
) -> HeldOutReplayWorkItem:
    return HeldOutReplayWorkItem(
        work_item_id=work_item_id,
        route_id=route_id,
        playbook_id=playbook_id,
        playbook_version="1.2",
        mechanism_class="breakout_continuation",
        dataset_snapshot_id="dataset-1",
        dataset_content_hash="a" * 64,
        fold_index=fold_index,
        test_start_utc=T0 + timedelta(days=fold_index * 10),
        test_end_utc=T0 + timedelta(days=fold_index * 10 + 9),
        code_commit_sha="b" * 40,
        configuration_hash="c" * 64,
    )


def _preflight(*works: HeldOutReplayWorkItem) -> HeldOutResearchRunnerPreflight:
    return HeldOutResearchRunnerPreflight(
        route_count=len({(w.route_id, w.playbook_id) for w in works}),
        routes=(),
        required_indicators=("ema",),
        required_asset_ids=("eurusd",),
        dataset_snapshot_id="dataset-1",
        fold_count=len({w.fold_index for w in works}),
        work_item_count=len(works),
        work_items=tuple(works),
        blockers=(),
    )


def test_exact_work_item_coverage_is_complete() -> None:
    one = _work(
        "work-1",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=0,
    )
    two = _work(
        "work-2",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=1,
    )
    results = (
        bind_replay_result(
            one,
            status=ReplayResultStatus.COMPLETE,
            immutable_trade_ids=("trade-1",),
        ),
        bind_replay_result(
            two,
            status=ReplayResultStatus.FAILED_EVIDENCE,
            immutable_trade_ids=("trade-2",),
        ),
    )

    report = require_complete_replay_result_coverage(
        _preflight(one, two),
        results,
    )
    assert report.complete is True
    assert report.expected_work_item_count == 2
    assert report.supplied_result_count == 2


def test_missing_work_item_is_visible_and_strict_mode_fails() -> None:
    one = _work(
        "work-1",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=0,
    )
    two = _work(
        "work-2",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=1,
    )
    result = bind_replay_result(
        one,
        status=ReplayResultStatus.COMPLETE,
        immutable_trade_ids=("trade-1",),
    )

    report = validate_replay_result_coverage(
        _preflight(one, two),
        (result,),
    )
    assert report.complete is False
    assert report.missing_work_item_ids == ("work-2",)

    with pytest.raises(ValueError, match="missing_work_items"):
        require_complete_replay_result_coverage(
            _preflight(one, two),
            (result,),
        )


def test_result_identity_and_hash_cannot_drift_from_work_item() -> None:
    work = _work(
        "work-1",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=0,
    )
    result = bind_replay_result(
        work,
        status=ReplayResultStatus.COMPLETE,
        immutable_trade_ids=("trade-1",),
    )

    bad = type(result)(
        work_item_id=result.work_item_id,
        route_id="eurusd:intraday:short",
        playbook_id=result.playbook_id,
        playbook_version=result.playbook_version,
        fold_index=result.fold_index,
        status=result.status,
        immutable_trade_ids=result.immutable_trade_ids,
        result_hash=result.result_hash,
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_replay_result_coverage(_preflight(work), (bad,))


def test_trade_id_cannot_be_counted_in_multiple_work_items() -> None:
    one = _work(
        "work-1",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=0,
    )
    two = _work(
        "work-2",
        route_id="eurusd:intraday:short",
        playbook_id="pb_fx_intraday_v1_2",
        fold_index=0,
    )
    results = (
        bind_replay_result(
            one,
            status=ReplayResultStatus.COMPLETE,
            immutable_trade_ids=("trade-shared",),
        ),
        bind_replay_result(
            two,
            status=ReplayResultStatus.COMPLETE,
            immutable_trade_ids=("trade-shared",),
        ),
    )
    report = validate_replay_result_coverage(
        _preflight(one, two),
        results,
    )
    assert report.complete is False
    assert report.duplicate_trade_ids == ("trade-shared",)


def test_nonstartable_preflight_cannot_accept_replay_results() -> None:
    preflight = HeldOutResearchRunnerPreflight(
        route_count=1,
        routes=(),
        required_indicators=("ema",),
        required_asset_ids=("eurusd",),
        dataset_snapshot_id=None,
        fold_count=0,
        work_item_count=0,
        work_items=(),
        blockers=("held_out_dataset_snapshot_required",),
    )
    with pytest.raises(ValueError, match="startable"):
        validate_replay_result_coverage(preflight, ())
