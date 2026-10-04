from __future__ import annotations

from datetime import datetime, timezone

from aether_vnext.market_fabric_observation import (
    CANONICAL_OBSERVATION_SCHEMA_VERSION,
    CanonicalMarketObservation,
    ObservationType,
    RawEnvelope,
    normalize_printed_fields,
    payload_sha256,
)


UTC = timezone.utc


def test_raw_hash_is_reproducible_and_sensitive_headers_are_not_persisted() -> None:
    payload = b'{"bid":"100.0","ask":"101.0"}'
    first = RawEnvelope.capture(
        raw_payload_ref="capture://fixture/1",
        payload=payload,
        provider_id="provider_x",
        transport_id="transport_x",
        adapter_id="aether.adapter.x",
        adapter_version="v1",
        provider_session_epoch="epoch-1",
        headers={
            "Authorization": "Bearer secret",
            "X-API-Key": "also-secret",
            "Content-Type": "application/json",
        },
    )
    second = RawEnvelope.capture(
        raw_payload_ref="capture://fixture/2",
        payload=payload,
        provider_id="provider_x",
        transport_id="transport_x",
        adapter_id="aether.adapter.x",
        adapter_version="v1",
        provider_session_epoch="epoch-1",
        headers={},
    )

    assert first.raw_payload_hash == second.raw_payload_hash == payload_sha256(payload)
    assert first.sanitized_headers["Authorization"] == "[REDACTED]"
    assert first.sanitized_headers["X-API-Key"] == "[REDACTED]"
    assert "secret" not in repr(first.sanitized_headers)


def test_missing_fields_remain_null_and_presence_distinguishes_omission() -> None:
    normalized, presence = normalize_printed_fields(
        {"b": 100.0, "a": 101.0, "last": None},
        field_map={
            "bid": "b",
            "ask": "a",
            "last": "last",
            "bid_size": "bs",
        },
    )

    assert normalized == {
        "bid": 100.0,
        "ask": 101.0,
        "last": None,
        "bid_size": None,
    }
    assert presence == frozenset({"bid", "ask", "last"})
    assert "bid_size" not in presence


def test_canonical_observation_preserves_transport_and_economic_source_identity() -> None:
    raw = b"book"
    obs = CanonicalMarketObservation(
        event_id="evt-1",
        market_id="crypto_spot_usd",
        asset_id="btc",
        instrument_id="btc_usd",
        venue_id="kraken",
        economic_source_id="kraken_spot",
        independence_group_id="venue:kraken",
        provider_id="kraken_direct",
        transport_id="kraken_ws",
        adapter_id="aether.adapter.kraken.ws",
        adapter_version="v1",
        observation_type=ObservationType.QUOTE,
        field_presence=frozenset({"bid", "ask"}),
        bid=100.0,
        ask=101.0,
        last=None,
        bid_size=None,
        ask_size=None,
        exchange_ts=None,
        vendor_ts=None,
        receive_ts=datetime(2026, 10, 4, tzinfo=UTC),
        native_sequence="42",
        native_event_id="native-42",
        raw_payload_hash=payload_sha256(raw),
        raw_payload_ref="capture://fixture/book",
    )

    assert obs.schema_version == CANONICAL_OBSERVATION_SCHEMA_VERSION
    assert obs.economic_source_id == "kraken_spot"
    assert obs.provider_id == "kraken_direct"
    assert obs.transport_id == "kraken_ws"
    assert obs.can_authorize_execution is False
