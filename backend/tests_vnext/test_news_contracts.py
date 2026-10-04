from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.news import (
    EventAssetLink,
    EventMarketResponse,
    HistoricalAnalogRun,
    NewsSource,
    NormalizedEvent,
    RawNewsItem,
    raw_news_identity_key,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _source(**overrides: object) -> NewsSource:
    kwargs: dict[str, object] = {
        "source_id": "fed",
        "source_name": "Federal Reserve",
        "source_class": "official_macro",
        "primary_or_secondary": "primary",
        "authority_class": "official",
        "base_timezone": "America/New_York",
        "provider_adapter_id": "fed-official-v1",
        "active": True,
        "terms_licensing_metadata_ref": "terms/fed",
    }
    kwargs.update(overrides)
    return NewsSource(**kwargs)


def _raw(**overrides: object) -> RawNewsItem:
    kwargs: dict[str, object] = {
        "news_item_id": "news-1",
        "source_id": "fed",
        "provider_item_id": "provider-1",
        "canonical_url": "https://example.test/item",
        "title": "Policy statement",
        "body_hash": "abc123",
        "published_at_utc": T0,
        "first_seen_at_utc": T0,
        "received_at_utc": T0,
        "revision_of_news_item_id": None,
        "correction_or_retraction": False,
        "language": "en",
        "ingest_status": "accepted",
        "dedupe_key": "dedupe-1",
        "raw_payload_ref": "payload/news-1",
    }
    kwargs.update(overrides)
    return RawNewsItem(**kwargs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("source_id", " fed ", "source_id must be canonical text"),
        ("provider_adapter_id", "", "provider_adapter_id must be canonical text"),
        ("active", 1, "active must be boolean"),
        (
            "terms_licensing_metadata_ref",
            " ",
            "terms_licensing_metadata_ref must be canonical text",
        ),
    ),
)
def test_news_source_rejects_noncanonical_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _source(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("news_item_id", " news-1 ", "news_item_id must be canonical text"),
        (
            "published_at_utc",
            T0.replace(tzinfo=None),
            "published_at_utc must be timezone-aware",
        ),
        (
            "first_seen_at_utc",
            T0.replace(tzinfo=None),
            "first_seen_at_utc must be timezone-aware",
        ),
        (
            "received_at_utc",
            T0.replace(tzinfo=None),
            "received_at_utc must be timezone-aware",
        ),
        (
            "correction_or_retraction",
            0,
            "correction_or_retraction must be boolean",
        ),
    ),
)
def test_raw_news_item_rejects_invalid_ingest_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _raw(**{field: value})


def test_raw_news_identity_key_rejects_noncanonical_or_naive_inputs() -> None:
    with pytest.raises(ValueError, match="source_id must be canonical text"):
        raw_news_identity_key(
            source_id=" fed ",
            provider_item_id="provider-1",
            canonical_url=None,
            published_at_utc=T0,
            normalized_title="policy statement",
        )

    with pytest.raises(ValueError, match="published_at_utc must be timezone-aware"):
        raw_news_identity_key(
            source_id="fed",
            provider_item_id=None,
            canonical_url="https://example.test/item",
            published_at_utc=T0.replace(tzinfo=None),
            normalized_title="policy statement",
        )


def _event(**overrides: object) -> NormalizedEvent:
    kwargs: dict[str, object] = {
        "event_id": "event-1",
        "event_cluster_id": "cluster-1",
        "event_type": "macro_release",
        "source_news_item_ids": ("news-1",),
        "assets": ("usd",),
        "clusters": ("rates",),
        "canonical_event_at_utc": T0,
        "information_available_at_utc": T0,
        "scheduled": True,
        "expected": True,
        "consensus": 2.0,
        "actual": 2.1,
        "surprise_magnitude": 0.1,
        "direction": "up",
        "severity": 0.5,
        "novelty": 0.2,
        "confidence": 0.9,
        "market_scope": "macro",
        "macro": True,
        "normalizer_version": "normalizer-v1",
    }
    kwargs.update(overrides)
    return NormalizedEvent(**kwargs)


def _link(**overrides: object) -> EventAssetLink:
    kwargs: dict[str, object] = {
        "event_id": "event-1",
        "asset_id": "usd",
        "relation_type": "direct",
        "confidence": 0.9,
        "evidence_source_ids": ("fed",),
        "created_at_utc": T0,
        "linker_version": "linker-v1",
    }
    kwargs.update(overrides)
    return EventAssetLink(**kwargs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("event_id", " event-1 ", "event_id must be canonical text"),
        (
            "canonical_event_at_utc",
            T0.replace(tzinfo=None),
            "canonical_event_at_utc must be timezone-aware",
        ),
        ("scheduled", 1, "scheduled must be boolean"),
        ("expected", 1, "expected must be boolean when present"),
        ("macro", 1, "macro must be boolean"),
        ("severity", True, "severity must be finite when present"),
    ),
)
def test_normalized_event_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _event(**{field: value})


def test_normalized_event_requires_immutable_canonical_identity_collections() -> None:
    with pytest.raises(ValueError, match="assets must be an immutable tuple"):
        _event(assets=["usd"])

    with pytest.raises(
        ValueError,
        match="source_news_item_ids entries must be canonical text",
    ):
        _event(source_news_item_ids=(" news-1 ",))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("event_id", " event-1 ", "event_id must be canonical text"),
        ("confidence", True, "confidence must be finite"),
        (
            "created_at_utc",
            T0.replace(tzinfo=None),
            "created_at_utc must be timezone-aware",
        ),
    ),
)
def test_event_asset_link_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _link(**{field: value})


def test_event_asset_link_requires_immutable_canonical_evidence_ids() -> None:
    with pytest.raises(ValueError, match="evidence_source_ids"):
        _link(evidence_source_ids=["fed"])

    with pytest.raises(ValueError, match="evidence_source_ids"):
        _link(evidence_source_ids=(" fed ",))


def _response(**overrides: object) -> EventMarketResponse:
    kwargs: dict[str, object] = {
        "event_id": "event-1",
        "asset_id": "btc",
        "pre_event_observation_id": "obs-pre-1",
        "return_1m": 0.01,
        "return_5m": 0.02,
        "return_15m": 0.03,
        "return_1h": 0.04,
        "return_4h": 0.05,
        "return_1d": 0.06,
        "mfe": 0.07,
        "mae": -0.02,
        "realized_vol_change": 0.01,
        "volume_change": 0.10,
        "spread_change": -0.01,
        "liquidity_change": 0.02,
        "correlation_change": 0.03,
        "continuation_or_reversal": "continuation",
        "stabilization_time": 300.0,
        "market_data_version": "market-v1",
    }
    kwargs.update(overrides)
    return EventMarketResponse(**kwargs)


def _analog(**overrides: object) -> HistoricalAnalogRun:
    kwargs: dict[str, object] = {
        "analog_run_id": "analog-1",
        "query_event_or_state_id": "event-1",
        "feature_spec_version": "features-v1",
        "as_of_utc": T0,
        "eligible_history_cutoff_utc": T0,
        "matched_event_ids": ("event-old-1",),
        "similarity_scores": (0.8,),
        "outcome_distribution": {"median_return_1h": 0.01},
        "created_at_utc": T0,
        "research_only": True,
    }
    kwargs.update(overrides)
    return HistoricalAnalogRun(**kwargs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("event_id", " event-1 ", "event_id must be canonical text"),
        ("return_1m", True, "return_1m must be finite when present"),
        ("mfe", float("nan"), "mfe must be finite when present"),
        (
            "continuation_or_reversal",
            " continuation ",
            "continuation_or_reversal must be canonical text",
        ),
    ),
)
def test_event_market_response_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _response(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "as_of_utc",
            T0.replace(tzinfo=None),
            "as_of_utc must be timezone-aware",
        ),
        ("research_only", False, "historical analog output is research_only"),
        (
            "matched_event_ids",
            ["event-old-1"],
            "matched_event_ids must be an immutable tuple",
        ),
        (
            "similarity_scores",
            (True,),
            "similarity_scores must be finite numerics",
        ),
    ),
)
def test_historical_analog_rejects_invalid_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _analog(**{field: value})


def test_historical_analog_enforces_alignment_and_no_lookahead_cutoff() -> None:
    with pytest.raises(
        ValueError,
        match="matched_event_ids and similarity_scores must align",
    ):
        _analog(
            matched_event_ids=("event-old-1", "event-old-2"),
            similarity_scores=(0.8,),
        )

    with pytest.raises(
        ValueError,
        match="history cutoff cannot be after as_of_utc",
    ):
        _analog(
            eligible_history_cutoff_utc=datetime(
                2026,
                9,
                1,
                12,
                1,
                tzinfo=UTC,
            )
        )


def test_provider_identity_key_remains_deterministic() -> None:
    first = raw_news_identity_key(
        source_id="fed",
        provider_item_id="provider-1",
        canonical_url=None,
        published_at_utc=T0,
        normalized_title="policy statement",
    )
    second = raw_news_identity_key(
        source_id="fed",
        provider_item_id="provider-1",
        canonical_url="https://ignored.example/item",
        published_at_utc=T0,
        normalized_title="different normalized title",
    )

    assert first == second
    assert len(first) == 64
