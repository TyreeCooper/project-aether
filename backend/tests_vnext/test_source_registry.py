from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.source_registry import (
    AssetSourceRecord,
    SourceTrustDecision,
    apply_trust_decision,
    summarize_source_registry,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 1, 20, tzinfo=UTC)


def _source(**overrides: object) -> AssetSourceRecord:
    kwargs: dict[str, object] = {
        "source_id": "btc:reddit:bitcoin",
        "asset_id": "btc",
        "source_type": "community",
        "platform": "reddit",
        "name": "r/Bitcoin",
        "url": "https://www.reddit.com/r/Bitcoin/",
        "tier": "B",
        "trust_state": "candidate",
        "origin": "curated_seed",
        "ingestion_mode": "shadow",
        "trade_influence_enabled": False,
        "operator_approved_by": None,
        "operator_approved_at_utc": None,
    }
    kwargs.update(overrides)
    return AssetSourceRecord(**kwargs)


def _decision(**overrides: object) -> SourceTrustDecision:
    kwargs: dict[str, object] = {
        "source_id": "btc:reddit:bitcoin",
        "prior_state": "candidate",
        "new_state": "trusted",
        "operator_id": "operator-1",
        "decided_at_utc": T0,
        "rationale": "approved for evidence handling",
    }
    kwargs.update(overrides)
    return SourceTrustDecision(**kwargs)


def test_candidate_source_starts_without_trade_authority() -> None:
    source = _source()
    assert source.trust_state == "candidate"
    assert source.trade_influence_enabled is False


def test_trusted_source_requires_explicit_operator_approval() -> None:
    with pytest.raises(
        ValueError,
        match="trusted source requires explicit operator approval",
    ):
        _source(trust_state="trusted")

    trusted = apply_trust_decision(_source(), _decision())
    assert trusted.trust_state == "trusted"
    assert trusted.operator_approved_by == "operator-1"
    assert trusted.operator_approved_at_utc == T0
    assert trusted.trade_influence_enabled is False


def test_trust_transition_requires_matching_source_and_prior_state() -> None:
    with pytest.raises(ValueError, match="source_id mismatch"):
        apply_trust_decision(
            _source(),
            _decision(source_id="eth:reddit:ethereum"),
        )

    with pytest.raises(ValueError, match="prior_state mismatch"):
        apply_trust_decision(
            _source(),
            _decision(prior_state="untrusted"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("asset_id", "BTC", "asset_id must be canonical lowercase"),
        ("source_id", " source ", "source_id must be canonical text"),
        ("trust_state", "auto_trusted", "invalid trust_state"),
        (
            "trade_influence_enabled",
            True,
            "source trust cannot enable trade influence",
        ),
    ),
)
def test_source_registry_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _source(**{field: value})


def test_trust_decision_requires_timezone_aware_operator_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="decided_at_utc must be timezone-aware",
    ):
        _decision(decided_at_utc=T0.replace(tzinfo=None))


def test_registry_summary_requires_immutable_tuple_and_never_enables_trade() -> None:
    candidate = _source()
    trusted = apply_trust_decision(candidate, _decision())

    summary = summarize_source_registry((candidate, trusted))
    assert summary["sources"] == 2
    assert summary["assets"] == 1
    assert summary["trust_states"]["candidate"] == 1
    assert summary["trust_states"]["trusted"] == 1
    assert summary["trade_influence_enabled"] is False

    with pytest.raises(ValueError, match="immutable tuple"):
        summarize_source_registry([candidate])
