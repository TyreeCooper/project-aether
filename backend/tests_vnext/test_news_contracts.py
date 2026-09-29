from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.news import (
    NewsSource,
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
