from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.held_out_research_runner import (
    REQUIRED_INDICATORS,
    HeldOutFoldPlan,
    HeldOutReplayInput,
    canonical_held_out_research_plan,
    canonical_held_out_required_asset_ids,
    preflight_canonical_held_out_research_runner,
)
from aether_vnext.research import ResearchDatasetSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
SHA40 = "a" * 40
HASH64 = "b" * 64


def _snapshot(
    *,
    asset_ids: tuple[str, ...] | None = None,
) -> ResearchDatasetSnapshot:
    return ResearchDatasetSnapshot(
        dataset_snapshot_id="dataset:canonical-heldout:v1",
        created_at_utc=T0 - timedelta(days=1),
        as_of_utc=T0,
        start_at_utc=T0 - timedelta(days=365),
        end_at_utc=T0 - timedelta(days=1),
        asset_ids=(
            canonical_held_out_required_asset_ids()
            if asset_ids is None
            else asset_ids
        ),
        data_version="reviewed-pit-history-v1",
        source_registry_version="reviewed-sources-v1",
        product_registry_version="aether-vnext-products-v1",
        calendar_version="reviewed-calendars-v1",
        pit=True,
        missing_data_policy="fail_closed",
        content_hash=HASH64,
    )


def _fold(
    index: int = 1,
    *,
    test_start_days_ago: int = 30,
    test_end_days_ago: int = 1,
) -> HeldOutFoldPlan:
    return HeldOutFoldPlan(
        fold_index=index,
        train_start_utc=T0 - timedelta(days=365),
        train_end_utc=T0 - timedelta(days=test_start_days_ago + 1),
        test_start_utc=T0 - timedelta(days=test_start_days_ago),
        test_end_utc=T0 - timedelta(days=test_end_days_ago),
    )


def test_canonical_research_plan_matches_74_route_burnin_universe() -> None:
    rows = canonical_held_out_research_plan()
    assert len(rows) == 74
    assert len(
        {(row.route_id, row.playbook_id) for row in rows}
    ) == 74
    assert all(row.playbook_version for row in rows)
    assert all(row.mechanism_class for row in rows)


def test_indicator_math_is_bound_but_real_replay_inputs_are_required() -> None:
    result = preflight_canonical_held_out_research_runner()

    assert result.startable is False
    assert result.route_count == 74
    assert result.required_indicators == REQUIRED_INDICATORS
    assert result.required_asset_ids == (
        "btc",
        "eth",
        "eurusd",
        "mcl",
        "mes",
        "mgc",
        "mnq",
        "nvda",
        "pltr",
        "tsla",
        "us10y",
        "usdjpy",
    )
    assert result.blockers == (
        "held_out_dataset_snapshot_required",
        "held_out_fold_plan_required",
        "held_out_code_commit_sha_required",
    )


def test_valid_real_input_builds_exact_route_fold_work_plan() -> None:
    input_ = HeldOutReplayInput(
        dataset_snapshot=_snapshot(),
        folds=(
            _fold(
                1,
                test_start_days_ago=60,
                test_end_days_ago=31,
            ),
            _fold(
                2,
                test_start_days_ago=30,
                test_end_days_ago=1,
            ),
        ),
        code_commit_sha=SHA40,
        configuration_hash=CONFIGURATION_HASH,
    )

    result = preflight_canonical_held_out_research_runner(input_)

    assert result.startable is True
    assert result.blockers == ()
    assert result.fold_count == 2
    assert result.work_item_count == 148
    assert len({row.work_item_id for row in result.work_items}) == 148
    assert {
        (row.route_id, row.playbook_id)
        for row in result.work_items
    } == {
        (row.route_id, row.playbook_id)
        for row in canonical_held_out_research_plan()
    }


def test_missing_required_dataset_asset_fails_closed() -> None:
    assets = tuple(
        asset
        for asset in canonical_held_out_required_asset_ids()
        if asset != "usdjpy"
    )
    result = preflight_canonical_held_out_research_runner(
        HeldOutReplayInput(
            dataset_snapshot=_snapshot(asset_ids=assets),
            folds=(_fold(),),
            code_commit_sha=SHA40,
            configuration_hash=CONFIGURATION_HASH,
        )
    )

    assert result.startable is False
    assert result.work_item_count == 0
    assert result.blockers == (
        "held_out_dataset_missing_assets:usdjpy",
    )


def test_overlapping_held_out_test_windows_fail_closed() -> None:
    first = _fold(
        1,
        test_start_days_ago=45,
        test_end_days_ago=15,
    )
    second = _fold(
        2,
        test_start_days_ago=20,
        test_end_days_ago=1,
    )
    result = preflight_canonical_held_out_research_runner(
        HeldOutReplayInput(
            dataset_snapshot=_snapshot(),
            folds=(first, second),
            code_commit_sha=SHA40,
            configuration_hash=CONFIGURATION_HASH,
        )
    )

    assert result.startable is False
    assert "held_out_fold_test_windows_overlap" in result.blockers


def test_configuration_drift_fails_closed() -> None:
    result = preflight_canonical_held_out_research_runner(
        HeldOutReplayInput(
            dataset_snapshot=_snapshot(),
            folds=(_fold(),),
            code_commit_sha=SHA40,
            configuration_hash="c" * 64,
        )
    )

    assert result.startable is False
    assert result.blockers == (
        "held_out_configuration_hash_mismatch",
    )


def test_prior_closed_range_remains_part_of_runner_contract() -> None:
    result = preflight_canonical_held_out_research_runner()
    assert "prior_closed_bar_range" in result.required_indicators
