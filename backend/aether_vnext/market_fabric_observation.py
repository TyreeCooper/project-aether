"""MF-02 canonical observation and raw-provenance contracts.

Provider-native objects terminate at the Market Fabric adapter boundary. The
canonical model preserves explicit field presence, source/transport identity, raw
payload lineage, and schema versioning without manufacturing missing values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
from types import MappingProxyType
from typing import Mapping


CANONICAL_OBSERVATION_SCHEMA_VERSION = "market-observation.v3.0"
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "api-key",
    }
)


def _required(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _aware(name: str, value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware when present")
    return value


def payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    return hashlib.sha256(payload).hexdigest()


def scrub_headers(headers: Mapping[str, str]) -> Mapping[str, str]:
    scrubbed = {
        str(key): (
            "[REDACTED]"
            if str(key).strip().lower() in _SENSITIVE_HEADER_NAMES
            else str(value)
        )
        for key, value in headers.items()
    }
    return MappingProxyType(dict(sorted(scrubbed.items())))


class ObservationType(StrEnum):
    QUOTE = "quote"
    TRADE = "trade"
    DEPTH = "depth"
    IMBALANCE = "imbalance"
    STATUS = "status"
    DEFINITION = "definition"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True, slots=True)
class RawEnvelope:
    raw_payload_ref: str
    raw_payload_hash: str
    provider_id: str
    transport_id: str
    adapter_id: str
    adapter_version: str
    provider_session_epoch: str | None
    sanitized_headers: Mapping[str, str]

    @classmethod
    def capture(
        cls,
        *,
        raw_payload_ref: str,
        payload: bytes,
        provider_id: str,
        transport_id: str,
        adapter_id: str,
        adapter_version: str,
        provider_session_epoch: str | None,
        headers: Mapping[str, str],
    ) -> "RawEnvelope":
        return cls(
            raw_payload_ref=_required("raw_payload_ref", raw_payload_ref),
            raw_payload_hash=payload_sha256(payload),
            provider_id=_required("provider_id", provider_id),
            transport_id=_required("transport_id", transport_id),
            adapter_id=_required("adapter_id", adapter_id),
            adapter_version=_required("adapter_version", adapter_version),
            provider_session_epoch=(
                None
                if provider_session_epoch is None
                else _required("provider_session_epoch", provider_session_epoch)
            ),
            sanitized_headers=scrub_headers(headers),
        )

    def __post_init__(self) -> None:
        if len(self.raw_payload_hash) != 64:
            raise ValueError("raw_payload_hash must be sha256 hex")
        if any(
            str(key).strip().lower() in _SENSITIVE_HEADER_NAMES
            and value != "[REDACTED]"
            for key, value in self.sanitized_headers.items()
        ):
            raise ValueError("sensitive headers must be redacted")


@dataclass(frozen=True, slots=True)
class CanonicalMarketObservation:
    event_id: str
    market_id: str
    asset_id: str
    instrument_id: str
    venue_id: str
    economic_source_id: str
    independence_group_id: str
    provider_id: str
    transport_id: str
    adapter_id: str
    adapter_version: str
    observation_type: ObservationType
    field_presence: frozenset[str]
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: float | None
    ask_size: float | None
    exchange_ts: datetime | None
    vendor_ts: datetime | None
    receive_ts: datetime
    native_sequence: str | None
    native_event_id: str | None
    raw_payload_hash: str
    raw_payload_ref: str
    schema_version: str = CANONICAL_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "market_id",
            "asset_id",
            "instrument_id",
            "venue_id",
            "economic_source_id",
            "independence_group_id",
            "provider_id",
            "transport_id",
            "adapter_id",
            "adapter_version",
            "raw_payload_hash",
            "raw_payload_ref",
            "schema_version",
        ):
            object.__setattr__(self, name, _required(name, getattr(self, name)))
        _aware("exchange_ts", self.exchange_ts)
        _aware("vendor_ts", self.vendor_ts)
        if self.receive_ts.tzinfo is None:
            raise ValueError("receive_ts must be timezone-aware")
        if len(self.raw_payload_hash) != 64:
            raise ValueError("raw_payload_hash must be sha256 hex")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")

        printed = {
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
        }
        for field_name, value in printed.items():
            if value is not None and field_name not in self.field_presence:
                raise ValueError(
                    f"{field_name} has a value but provider field presence was not recorded"
                )

    @property
    def can_authorize_execution(self) -> bool:
        return False


def normalize_printed_fields(
    payload: Mapping[str, object],
    *,
    field_map: Mapping[str, str],
) -> tuple[dict[str, object | None], frozenset[str]]:
    """Map only provider fields that actually exist.

    No averaging, fallback, carry-forward, or cross-source calculation is permitted
    at this boundary. Explicit provider null and provider omission remain
    distinguishable through field_presence.
    """
    normalized: dict[str, object | None] = {}
    presence: set[str] = set()
    for canonical_name, provider_name in field_map.items():
        if provider_name in payload:
            presence.add(canonical_name)
            normalized[canonical_name] = payload[provider_name]
        else:
            normalized[canonical_name] = None
    return normalized, frozenset(presence)
