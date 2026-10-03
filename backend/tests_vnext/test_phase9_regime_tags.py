from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.regime import RegimeTags


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 22, 45, tzinfo=UTC)


def test_regime_tags_require_all_six_source_bound_families() -> None:
    tags = RegimeTags(
        trend_range="trend",
        realized_volatility_band="mid",
        session="ny",
        spread_cost_band="normal",
        event_risk_state="normal",
        data_quality_state="healthy",
        as_of_utc=T0,
    )
    assert RegimeTags.from_payload(tags.to_payload()) == tags


def test_blank_family_and_naive_or_future_timestamp_fail_closed() -> None:
    with pytest.raises(ValueError, match="trend_range"):
        RegimeTags(
            trend_range="",
            realized_volatility_band="mid",
            session="ny",
            spread_cost_band="normal",
            event_risk_state="normal",
            data_quality_state="healthy",
            as_of_utc=T0,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        RegimeTags(
            trend_range="trend",
            realized_volatility_band="mid",
            session="ny",
            spread_cost_band="normal",
            event_risk_state="normal",
            data_quality_state="healthy",
            as_of_utc=T0.replace(tzinfo=None),
        )

    tags = RegimeTags(
        trend_range="trend",
        realized_volatility_band="mid",
        session="ny",
        spread_cost_band="normal",
        event_risk_state="normal",
        data_quality_state="healthy",
        as_of_utc=T0,
    )
    with pytest.raises(ValueError, match="future information"):
        tags.assert_point_in_time(
            no_later_than_utc=T0.replace(minute=44)
        )
