from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.source_candidates import (
    CandidateReview,
    SourceCandidate,
    stage_candidate_as_source,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 7, 30, tzinfo=UTC)


def _candidate(**overrides: object) -> SourceCandidate:
    kwargs: dict[str, object] = {
        "candidate_id": "btc:official:example",
        "asset_id": "btc",
        "source_type": "official",
        "platform": "web",
        "name": "Example official source",
        "url": "https://example.test/btc",
        "tier": "A",
        "discovery_origin": "candidate_discovery",
        "ingestion_mode": "shadow",
        "discovered_at_utc": T0,
        "evidence_ref": "discovery/btc/example",
        "trade_influence_enabled": False,
    }
    kwargs.update(overrides)
    return SourceCandidate(**kwargs)


def _review(**overrides: object) -> CandidateReview:
    kwargs: dict[str, object] = {
        "candidate_id": "btc:official:example",
        "reviewed_by": "operator-1",
        "reviewed_at_utc": T0,
        "accepted_for_registry": True,
        "rationale": "approved for candidate registry only",
    }
    kwargs.update(overrides)
    return CandidateReview(**kwargs)


def test_operator_accepted_candidate_can_only_enter_as_candidate() -> None:
    source = stage_candidate_as_source(_candidate(), _review())

    assert source.trust_state == "candidate"
    assert source.operator_approved_by is None
    assert source.operator_approved_at_utc is None
    assert source.trade_influence_enabled is False


def test_rejected_candidate_cannot_enter_registry() -> None:
    with pytest.raises(
        ValueError,
        match="candidate requires operator acceptance",
    ):
        stage_candidate_as_source(
            _candidate(),
            _review(accepted_for_registry=False),
        )


def test_candidate_review_identity_must_match() -> None:
    with pytest.raises(
        ValueError,
        match="candidate review identity mismatch",
    ):
        stage_candidate_as_source(
            _candidate(),
            _review(candidate_id="eth:official:example"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("candidate_id", " candidate ", "candidate_id must be canonical text"),
        ("asset_id", "BTC", "asset_id must be canonical lowercase"),
        (
            "discovered_at_utc",
            T0.replace(tzinfo=None),
            "discovered_at_utc must be timezone-aware",
        ),
        (
            "trade_influence_enabled",
            True,
            "source candidate cannot enable trade influence",
        ),
    ),
)
def test_candidate_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _candidate(**{field: value})


def test_candidate_review_requires_explicit_boolean_and_aware_time() -> None:
    with pytest.raises(
        ValueError,
        match="accepted_for_registry must be boolean",
    ):
        _review(accepted_for_registry=1)

    with pytest.raises(
        ValueError,
        match="reviewed_at_utc must be timezone-aware",
    ):
        _review(reviewed_at_utc=T0.replace(tzinfo=None))
