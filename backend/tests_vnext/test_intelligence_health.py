from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.intelligence_health import (
    SourceClaim,
    SourceHealthInput,
    assess_cross_source_conflict,
    derive_source_health,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 29, 5, 30, tzinfo=UTC)


def _health(**overrides: object) -> SourceHealthInput:
    kwargs: dict[str, object] = {
        "source_id": "macro:fed",
        "configured": True,
        "observed_at_utc": NOW,
        "last_success_at_utc": NOW - timedelta(seconds=30),
        "stale_after_seconds": 60,
        "degraded": False,
        "coverage_complete": True,
        "last_error": None,
    }
    kwargs.update(overrides)
    return SourceHealthInput(**kwargs)


def _claim(
    source_id: str,
    fingerprint: str,
    *,
    claim_key: str = "macro:fomc:2026-09",
) -> SourceClaim:
    return SourceClaim(
        source_id=source_id,
        claim_key=claim_key,
        value_fingerprint=fingerprint,
        observed_at_utc=NOW,
    )


@pytest.mark.parametrize(
    ("input_overrides", "expected_state"),
    (
        ({"configured": False}, "unconfigured"),
        ({"degraded": True}, "degraded"),
        ({"last_success_at_utc": None}, "unavailable"),
        (
            {
                "last_success_at_utc": NOW - timedelta(seconds=61),
                "stale_after_seconds": 60,
            },
            "stale",
        ),
        ({"coverage_complete": False}, "partial"),
        ({}, "healthy"),
    ),
)
def test_source_health_preserves_distinct_states(
    input_overrides: dict[str, object],
    expected_state: str,
) -> None:
    snapshot = derive_source_health(_health(**input_overrides))
    assert snapshot.state == expected_state
    assert snapshot.trade_influence_enabled is False


def test_source_health_uses_caller_supplied_freshness_threshold_exactly() -> None:
    at_threshold = derive_source_health(
        _health(
            last_success_at_utc=NOW - timedelta(seconds=60),
            stale_after_seconds=60,
        )
    )
    beyond_threshold = derive_source_health(
        _health(
            last_success_at_utc=NOW - timedelta(seconds=61),
            stale_after_seconds=60,
        )
    )

    assert at_threshold.state == "healthy"
    assert beyond_threshold.state == "stale"


def test_source_health_rejects_invalid_time_and_threshold_contracts() -> None:
    with pytest.raises(
        ValueError,
        match="stale_after_seconds must be a positive integer",
    ):
        _health(stale_after_seconds=True)

    with pytest.raises(
        ValueError,
        match="last_success_at_utc cannot follow observed_at_utc",
    ):
        _health(last_success_at_utc=NOW + timedelta(seconds=1))

    with pytest.raises(
        ValueError,
        match="observed_at_utc must be timezone-aware",
    ):
        _health(observed_at_utc=NOW.replace(tzinfo=None))


def test_cross_source_conflict_requires_independent_sources() -> None:
    insufficient = assess_cross_source_conflict(
        "macro:fomc:2026-09",
        (_claim("fed", "hash-a"),),
        assessed_at_utc=NOW,
    )
    assert insufficient.state == "insufficient"

    aligned = assess_cross_source_conflict(
        "macro:fomc:2026-09",
        (
            _claim("fed", "hash-a"),
            _claim("aggregator", "hash-a"),
        ),
        assessed_at_utc=NOW,
    )
    assert aligned.state == "aligned"
    assert aligned.trade_influence_enabled is False

    conflict = assess_cross_source_conflict(
        "macro:fomc:2026-09",
        (
            _claim("fed", "hash-a"),
            _claim("aggregator", "hash-b"),
        ),
        assessed_at_utc=NOW,
    )
    assert conflict.state == "conflict"
    assert conflict.value_fingerprints == ("hash-a", "hash-b")
    assert conflict.trade_influence_enabled is False


def test_conflict_assessment_scopes_claims_by_exact_key() -> None:
    result = assess_cross_source_conflict(
        "macro:fomc:2026-09",
        (
            _claim("fed", "hash-a"),
            _claim(
                "bea",
                "hash-b",
                claim_key="macro:gdp:2026-q3",
            ),
        ),
        assessed_at_utc=NOW,
    )

    assert result.state == "insufficient"
    assert result.source_ids == ("fed",)
    assert result.value_fingerprints == ("hash-a",)


def test_conflict_assessment_requires_immutable_claim_collection() -> None:
    with pytest.raises(ValueError, match="claims must be an immutable tuple"):
        assess_cross_source_conflict(
            "macro:fomc:2026-09",
            [_claim("fed", "hash-a")],
            assessed_at_utc=NOW,
        )
