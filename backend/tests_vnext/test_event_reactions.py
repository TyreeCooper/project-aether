from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.event_reactions import (
    EVENT_REACTION_HORIZONS,
    EventReactionMeasurement,
    EventReactionRollup,
    materialize_event_reaction_rollup,
)


UTC = timezone.utc
EVENT_AT = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
INFO_AT = EVENT_AT


def _measurement(
    label: str = "5m",
    *,
    event_id: str = "event-1",
    asset_id: str = "btc",
    market_data_version: str = "market-v1",
    observed_at_utc: datetime | None = None,
    return_value: float = 0.01,
    research_only: bool = True,
) -> EventReactionMeasurement:
    horizons = dict(EVENT_REACTION_HORIZONS)
    seconds = horizons[label]
    observed = (
        EVENT_AT + timedelta(seconds=seconds)
        if observed_at_utc is None
        else observed_at_utc
    )
    return EventReactionMeasurement(
        event_id=event_id,
        asset_id=asset_id,
        event_at_utc=EVENT_AT,
        information_available_at_utc=INFO_AT,
        horizon_seconds=seconds,
        observed_at_utc=observed,
        return_value=return_value,
        observation_id=f"obs-{label}",
        market_data_version=market_data_version,
        research_only=research_only,
    )


def test_materialized_rollup_covers_canonical_six_windows() -> None:
    rows = tuple(
        _measurement(label)
        for label, _ in EVENT_REACTION_HORIZONS
    )
    materialized = materialize_event_reaction_rollup(
        rows,
        materialized_at_utc=EVENT_AT + timedelta(hours=24),
    )

    assert materialized.complete is True
    assert tuple(materialized.returns_by_horizon()) == (
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "24h",
    )
    assert materialized.research_only is True


def test_partial_rollup_is_allowed_but_not_marked_complete() -> None:
    rollup = materialize_event_reaction_rollup(
        (_measurement("5m"), _measurement("1h")),
        materialized_at_utc=EVENT_AT + timedelta(hours=1),
    )

    assert rollup.complete is False
    assert rollup.returns_by_horizon() == {
        "5m": 0.01,
        "1h": 0.01,
    }


def test_measurement_rejects_noncanonical_horizon_and_boolean_return() -> None:
    with pytest.raises(
        ValueError,
        match="canonical event-reaction horizon",
    ):
        EventReactionMeasurement(
            event_id="event-1",
            asset_id="btc",
            event_at_utc=EVENT_AT,
            information_available_at_utc=INFO_AT,
            horizon_seconds=600,
            observed_at_utc=EVENT_AT + timedelta(minutes=10),
            return_value=0.01,
            observation_id="obs-10m",
            market_data_version="market-v1",
        )

    with pytest.raises(ValueError, match="return_value must be finite numeric"):
        _measurement(return_value=True)


def test_measurement_enforces_information_and_horizon_timing() -> None:
    with pytest.raises(
        ValueError,
        match="cannot precede information availability",
    ):
        EventReactionMeasurement(
            event_id="event-1",
            asset_id="btc",
            event_at_utc=EVENT_AT,
            information_available_at_utc=EVENT_AT + timedelta(minutes=10),
            horizon_seconds=5 * 60,
            observed_at_utc=EVENT_AT + timedelta(minutes=5),
            return_value=0.01,
            observation_id="obs-5m",
            market_data_version="market-v1",
        )

    with pytest.raises(
        ValueError,
        match="cannot precede its horizon target",
    ):
        _measurement(
            "15m",
            observed_at_utc=EVENT_AT + timedelta(minutes=14),
        )


def test_rollup_rejects_lineage_drift_and_duplicate_horizons() -> None:
    first = _measurement("5m")
    wrong_asset = _measurement("15m", asset_id="eth")

    with pytest.raises(
        ValueError,
        match="reaction measurement asset_id mismatch",
    ):
        EventReactionRollup(
            event_id="event-1",
            asset_id="btc",
            event_at_utc=EVENT_AT,
            information_available_at_utc=INFO_AT,
            market_data_version="market-v1",
            measurements=(first, wrong_asset),
            materialized_at_utc=EVENT_AT + timedelta(minutes=15),
        )

    duplicate = EventReactionMeasurement(
        event_id=first.event_id,
        asset_id=first.asset_id,
        event_at_utc=first.event_at_utc,
        information_available_at_utc=first.information_available_at_utc,
        horizon_seconds=first.horizon_seconds,
        observed_at_utc=first.observed_at_utc + timedelta(seconds=1),
        return_value=0.02,
        observation_id="obs-5m-duplicate",
        market_data_version=first.market_data_version,
    )
    with pytest.raises(ValueError, match="duplicate event-reaction horizon"):
        materialize_event_reaction_rollup(
            (first, duplicate),
            materialized_at_utc=EVENT_AT + timedelta(minutes=6),
        )


def test_rollup_cannot_materialize_before_latest_observation() -> None:
    row = _measurement("1h")
    with pytest.raises(
        ValueError,
        match="materialization cannot precede reaction observation",
    ):
        materialize_event_reaction_rollup(
            (row,),
            materialized_at_utc=EVENT_AT + timedelta(minutes=59),
        )


def test_reaction_outputs_remain_research_only() -> None:
    with pytest.raises(
        ValueError,
        match="event reaction measurement is research_only",
    ):
        _measurement(research_only=False)

    row = _measurement("5m")
    with pytest.raises(
        ValueError,
        match="event reaction rollup is research_only",
    ):
        EventReactionRollup(
            event_id="event-1",
            asset_id="btc",
            event_at_utc=EVENT_AT,
            information_available_at_utc=INFO_AT,
            market_data_version="market-v1",
            measurements=(row,),
            materialized_at_utc=EVENT_AT + timedelta(minutes=5),
            research_only=False,
        )
