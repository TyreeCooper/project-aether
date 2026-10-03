from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bars import Bar
from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.family_b import FamilyBEvaluation
from aether_vnext.family_c import FamilyCEvaluation
from aether_vnext.playbooks import PlaybookFamily
from aether_vnext.runtime_cycle import (
    ClosedBarCycleInput,
    evaluate_closed_bar_cycle,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 7, 0, tzinfo=UTC)


def _bar(*, asset_id: str = "eurusd") -> Bar:
    return Bar(
        asset_id=asset_id,
        interval=timedelta(minutes=15),
        bucket_open_utc=T0,
        bucket_close_utc=T0 + timedelta(minutes=15),
        open=1.1000,
        high=1.1010,
        low=1.0990,
        close=1.1005,
        volume=10.0,
        first_exchange_ts=T0 + timedelta(seconds=1),
        last_exchange_ts=T0 + timedelta(minutes=14, seconds=59),
        print_count=10,
        source_id="test",
    )


def _family_a(*, structure: bool, watch: bool) -> FamilyAEvaluation:
    return FamilyAEvaluation(
        playbook_id="pb_fx_intraday_v1_2",
        asset_id="eurusd",
        side="long",
        definition_enabled=True,
        regime_eligible=True,
        structure_rule=structure,
        dependency_ok=watch,
    )


def _family_b(*, structure: bool) -> FamilyBEvaluation:
    return FamilyBEvaluation(
        playbook_id="pb_fx_failed_session_v1_3",
        asset_id="eurusd",
        side="long",
        definition_enabled=True,
        regime_eligible=True,
        fail_window_bars=4,
        within_fail_window=True,
        silent_existing_open=False,
        structure_rule=structure,
        locate_ok=True,
    )


def _family_c(*, structure: bool) -> FamilyCEvaluation:
    return FamilyCEvaluation(
        playbook_id="pb_fx_range_v1_3",
        asset_id="eurusd",
        side="long",
        definition_enabled=True,
        regime_eligible=True,
        outside_prior_range=True,
        trend_not_confirming=True,
        structure_rule=structure,
    )


def test_cycle_applies_existing_family_precedence_on_one_closed_bar() -> None:
    cycle = ClosedBarCycleInput(
        asset_id="eurusd",
        horizon="intraday",
        trigger_bar=_bar(),
        family_a=(_family_a(structure=True, watch=True),),
        family_b=(_family_b(structure=True),),
        family_c=(_family_c(structure=True),),
    )

    result = evaluate_closed_bar_cycle(cycle)

    assert result.asset_id == "eurusd"
    assert result.horizon == "intraday"
    assert result.trigger_bar_close_utc == T0 + timedelta(minutes=15)
    assert result.decision.selected_family is PlaybookFamily.A
    assert result.decision.reason == "family_a_structure_precedence"
    assert tuple(
        row.playbook_id for row in result.decision.watch_candidates
    ) == ("pb_fx_intraday_v1_2",)
    assert set(result.decision.suppressed_by_precedence) == {
        "pb_fx_failed_session_v1_3",
        "pb_fx_range_v1_3",
    }


def test_cycle_returns_structure_fail_when_no_family_has_structure() -> None:
    cycle = ClosedBarCycleInput(
        asset_id="eurusd",
        horizon="intraday",
        trigger_bar=_bar(),
        family_a=(_family_a(structure=False, watch=True),),
        family_b=(_family_b(structure=False),),
        family_c=(_family_c(structure=False),),
    )

    result = evaluate_closed_bar_cycle(cycle)

    assert result.decision.selected_family is None
    assert result.decision.reason == "structure_fail"
    assert result.decision.watch_candidates == ()


def test_cycle_rejects_trigger_bar_asset_mismatch() -> None:
    with pytest.raises(ValueError, match="asset_id mismatch"):
        ClosedBarCycleInput(
            asset_id="eurusd",
            horizon="intraday",
            trigger_bar=_bar(asset_id="usdjpy"),
        )


def test_cycle_does_not_accept_forming_bar_timestamp() -> None:
    bar = _bar()
    invalid = Bar(
        asset_id=bar.asset_id,
        interval=bar.interval,
        bucket_open_utc=bar.bucket_open_utc,
        bucket_close_utc=bar.bucket_close_utc,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        first_exchange_ts=bar.first_exchange_ts,
        last_exchange_ts=bar.bucket_close_utc,
        print_count=bar.print_count,
        source_id=bar.source_id,
    )
    with pytest.raises(ValueError, match="precede bucket close"):
        ClosedBarCycleInput(
            asset_id="eurusd",
            horizon="intraday",
            trigger_bar=invalid,
        )
