"""Durable shortability/locate evidence contract for AETHER vNext.

Borrow availability is time-varying execution infrastructure, not static Product
Registry truth. A configured provider name alone cannot authorize an equity short.
This module evaluates immutable provider evidence against the reviewed runtime
binding at the instant Portfolio attempts READY -> RESERVED.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json


@dataclass(frozen=True, slots=True)
class ShortabilityEvidence:
    evidence_id: str
    asset_id: str
    provider_id: str
    market_data_contract_id: int
    shortable_shares: float
    fee_rate_raw: str | None
    shortable_raw: str | None
    market_data_availability: str
    provider_updated_at_utc: datetime | None
    received_at_utc: datetime
    adapter_version: str

    def __post_init__(self) -> None:
        if not str(self.evidence_id).strip():
            raise ValueError("evidence_id is required")
        if not str(self.asset_id).strip():
            raise ValueError("asset_id is required")
        if not str(self.provider_id).strip():
            raise ValueError("provider_id is required")
        if (
            isinstance(self.market_data_contract_id, bool)
            or self.market_data_contract_id <= 0
        ):
            raise ValueError("market_data_contract_id must be positive")
        if self.shortable_shares < 0:
            raise ValueError("shortable_shares cannot be negative")
        if not str(self.market_data_availability).strip():
            raise ValueError("market_data_availability is required")
        if self.provider_updated_at_utc is not None and (
            self.provider_updated_at_utc.tzinfo is None
        ):
            raise ValueError("provider_updated_at_utc must be timezone-aware")
        if self.received_at_utc.tzinfo is None:
            raise ValueError("received_at_utc must be timezone-aware")
        if not str(self.adapter_version).strip():
            raise ValueError("adapter_version is required")


@dataclass(frozen=True, slots=True)
class ShortabilityDecision:
    allowed: bool
    reason: str
    evidence_id: str | None
    age_ms: int | None
    available_shares: float | None


def shortability_evidence_id(
    *,
    asset_id: str,
    provider_id: str,
    market_data_contract_id: int,
    shortable_shares: float,
    fee_rate_raw: str | None,
    shortable_raw: str | None,
    market_data_availability: str,
    provider_updated_at_utc: datetime | None,
    received_at_utc: datetime,
    adapter_version: str,
) -> str:
    payload = {
        "asset_id": str(asset_id).strip().lower(),
        "provider_id": str(provider_id).strip(),
        "market_data_contract_id": int(market_data_contract_id),
        "shortable_shares": float(shortable_shares),
        "fee_rate_raw": None if fee_rate_raw is None else str(fee_rate_raw),
        "shortable_raw": None if shortable_raw is None else str(shortable_raw),
        "market_data_availability": str(market_data_availability).strip(),
        "provider_updated_at_utc": (
            None
            if provider_updated_at_utc is None
            else provider_updated_at_utc.isoformat()
        ),
        "received_at_utc": received_at_utc.isoformat(),
        "adapter_version": str(adapter_version).strip(),
    }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_shortability_evidence(
    *,
    asset_id: str,
    provider_id: str,
    market_data_contract_id: int,
    shortable_shares: float,
    fee_rate_raw: str | None,
    shortable_raw: str | None,
    market_data_availability: str,
    provider_updated_at_utc: datetime | None,
    received_at_utc: datetime,
    adapter_version: str,
) -> ShortabilityEvidence:
    evidence_id = shortability_evidence_id(
        asset_id=asset_id,
        provider_id=provider_id,
        market_data_contract_id=market_data_contract_id,
        shortable_shares=shortable_shares,
        fee_rate_raw=fee_rate_raw,
        shortable_raw=shortable_raw,
        market_data_availability=market_data_availability,
        provider_updated_at_utc=provider_updated_at_utc,
        received_at_utc=received_at_utc,
        adapter_version=adapter_version,
    )
    return ShortabilityEvidence(
        evidence_id=evidence_id,
        asset_id=str(asset_id).strip().lower(),
        provider_id=str(provider_id).strip(),
        market_data_contract_id=int(market_data_contract_id),
        shortable_shares=float(shortable_shares),
        fee_rate_raw=(
            None if fee_rate_raw is None else str(fee_rate_raw).strip() or None
        ),
        shortable_raw=(
            None if shortable_raw is None else str(shortable_raw).strip() or None
        ),
        market_data_availability=str(market_data_availability).strip(),
        provider_updated_at_utc=provider_updated_at_utc,
        received_at_utc=received_at_utc,
        adapter_version=str(adapter_version).strip(),
    )


def evaluate_shortability(
    evidence: ShortabilityEvidence | None,
    *,
    expected_asset_id: str,
    expected_provider_id: str,
    expected_contract_id: int,
    requested_shares: float,
    as_of_utc: datetime,
    max_age_ms: int,
) -> ShortabilityDecision:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if requested_shares <= 0:
        raise ValueError("requested_shares must be positive")
    if max_age_ms <= 0:
        raise ValueError("max_age_ms must be positive")

    if evidence is None:
        return ShortabilityDecision(
            False,
            "shortability_evidence_missing",
            None,
            None,
            None,
        )

    if evidence.asset_id != str(expected_asset_id).strip().lower():
        return ShortabilityDecision(
            False,
            "shortability_asset_mismatch",
            evidence.evidence_id,
            None,
            evidence.shortable_shares,
        )
    if evidence.provider_id != str(expected_provider_id).strip():
        return ShortabilityDecision(
            False,
            "shortability_provider_mismatch",
            evidence.evidence_id,
            None,
            evidence.shortable_shares,
        )
    if evidence.market_data_contract_id != int(expected_contract_id):
        return ShortabilityDecision(
            False,
            "shortability_contract_mismatch",
            evidence.evidence_id,
            None,
            evidence.shortable_shares,
        )

    availability = evidence.market_data_availability
    if not availability or availability[0] != "R":
        return ShortabilityDecision(
            False,
            "shortability_not_realtime",
            evidence.evidence_id,
            None,
            evidence.shortable_shares,
        )

    reference = evidence.provider_updated_at_utc or evidence.received_at_utc
    age_ms = int((as_of_utc - reference).total_seconds() * 1000)
    if age_ms < 0:
        return ShortabilityDecision(
            False,
            "shortability_timestamp_in_future",
            evidence.evidence_id,
            age_ms,
            evidence.shortable_shares,
        )
    if age_ms > int(max_age_ms):
        return ShortabilityDecision(
            False,
            "shortability_evidence_stale",
            evidence.evidence_id,
            age_ms,
            evidence.shortable_shares,
        )
    if evidence.shortable_shares + 1e-12 < float(requested_shares):
        return ShortabilityDecision(
            False,
            "shortability_insufficient_shares",
            evidence.evidence_id,
            age_ms,
            evidence.shortable_shares,
        )

    return ShortabilityDecision(
        True,
        "shortability_available",
        evidence.evidence_id,
        age_ms,
        evidence.shortable_shares,
    )
