"""Durable runtime Product Registry binding contract for AETHER vNext.

Frozen economic identity lives in registry.py. This module carries only external,
time-varying facts that must be bound before a product can participate in a real
forward-paper campaign: executable symbol, market-data source/freshness policy,
calendar provider, futures contract lifecycle, and (for borrow-required equities)
a shortability/locate provider identity.

No provider, symbol, stale threshold, contract, expiry, or locate source is invented.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json

from aether_vnext.calendar_sources import (
    calendar_provider_implementation_blockers,
)
from aether_vnext.market_sources import market_source_implementation_blockers
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.registry import (
    ProductRegistryRow,
    bind_futures_contract,
    bind_market_data,
    registry_row,
    validate_registry_row,
)


@dataclass(frozen=True, slots=True)
class RuntimeRegistryBinding:
    asset_id: str
    broker_symbol: str | None
    primary_market_source_id: str | None
    stale_threshold_ms: int | None
    calendar_provider_id: str | None
    fallback_market_source_id: str | None = None
    current_contract: str | None = None
    market_data_contract_id: int | None = None
    expiry_utc: datetime | None = None
    next_contract: str | None = None
    shortability_provider_id: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if not str(self.asset_id).strip():
            raise ValueError("asset_id is required")
        if self.stale_threshold_ms is not None and self.stale_threshold_ms <= 0:
            raise ValueError("stale_threshold_ms must be positive")
        if (
            self.market_data_contract_id is not None
            and (
                isinstance(self.market_data_contract_id, bool)
                or self.market_data_contract_id <= 0
            )
        ):
            raise ValueError("market_data_contract_id must be a positive integer")
        if self.expiry_utc is not None and self.expiry_utc.tzinfo is None:
            raise ValueError("expiry_utc must be timezone-aware")


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def binding_payload(binding: RuntimeRegistryBinding) -> dict[str, object]:
    return {
        "asset_id": binding.asset_id.strip().lower(),
        "broker_symbol": _clean(binding.broker_symbol),
        "primary_market_source_id": _clean(binding.primary_market_source_id),
        "fallback_market_source_id": _clean(binding.fallback_market_source_id),
        "stale_threshold_ms": binding.stale_threshold_ms,
        "calendar_provider_id": _clean(binding.calendar_provider_id),
        "current_contract": _clean(binding.current_contract),
        "market_data_contract_id": binding.market_data_contract_id,
        "expiry_utc": (
            binding.expiry_utc.isoformat()
            if binding.expiry_utc is not None
            else None
        ),
        "next_contract": _clean(binding.next_contract),
        "shortability_provider_id": _clean(binding.shortability_provider_id),
        "source_ref": _clean(binding.source_ref),
    }


def binding_hash(binding: RuntimeRegistryBinding) -> str:
    raw = json.dumps(
        binding_payload(binding),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def binding_from_payload(payload: dict[str, object]) -> RuntimeRegistryBinding:
    expiry_raw = payload.get("expiry_utc")
    expiry = None
    if expiry_raw is not None:
        expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
    stale_raw = payload.get("stale_threshold_ms")
    stale = None if stale_raw is None else int(stale_raw)
    contract_id_raw = payload.get("market_data_contract_id")
    market_data_contract_id = (
        None if contract_id_raw is None else int(contract_id_raw)
    )
    return RuntimeRegistryBinding(
        asset_id=str(payload.get("asset_id") or ""),
        broker_symbol=_clean(payload.get("broker_symbol")),
        primary_market_source_id=_clean(payload.get("primary_market_source_id")),
        fallback_market_source_id=_clean(payload.get("fallback_market_source_id")),
        stale_threshold_ms=stale,
        calendar_provider_id=_clean(payload.get("calendar_provider_id")),
        current_contract=_clean(payload.get("current_contract")),
        market_data_contract_id=market_data_contract_id,
        expiry_utc=expiry,
        next_contract=_clean(payload.get("next_contract")),
        shortability_provider_id=_clean(payload.get("shortability_provider_id")),
        source_ref=_clean(payload.get("source_ref")),
    )


def binding_blockers(
    binding: RuntimeRegistryBinding,
    *,
    as_of_utc: datetime | None = None,
    require_market_source_implementation: bool = False,
    require_calendar_provider_implementation: bool = False,
) -> tuple[str, ...]:
    """Return exact missing/unsafe external binding facts for one seed asset."""
    asset_id = binding.asset_id.strip().lower()
    try:
        base = registry_row(asset_id)
    except KeyError:
        return ("unknown_asset_id",)

    blockers: list[str] = []
    broker_symbol = _clean(binding.broker_symbol)
    if broker_symbol is None:
        blockers.append("runtime_broker_symbol_missing")
    primary_source_id = _clean(binding.primary_market_source_id)
    fallback_source_id = _clean(binding.fallback_market_source_id)
    if primary_source_id is None:
        blockers.append("market_data_source_missing")
    elif require_market_source_implementation:
        blockers.extend(
            market_source_implementation_blockers(
                source_id=primary_source_id,
                asset_id=asset_id,
                role="primary",
            )
        )
    if (
        fallback_source_id is not None
        and require_market_source_implementation
    ):
        blockers.extend(
            market_source_implementation_blockers(
                source_id=fallback_source_id,
                asset_id=asset_id,
                role="fallback",
            )
        )
    if binding.stale_threshold_ms is None:
        blockers.append("stale_threshold_missing")

    if base.calendar_id != "crypto_24x7":
        calendar_provider_id = _clean(binding.calendar_provider_id)
        if calendar_provider_id is None:
            blockers.append("calendar_provider_missing")
        elif require_calendar_provider_implementation:
            blockers.extend(
                calendar_provider_implementation_blockers(
                    calendar_id=base.calendar_id,
                    provider_id=calendar_provider_id,
                )
            )

    if base.borrow_required and _clean(binding.shortability_provider_id) is None:
        blockers.append("shortability_provider_missing")

    futures = base.futures_lifecycle is not None
    if futures:
        current_contract = _clean(binding.current_contract)
        next_contract = _clean(binding.next_contract)
        if current_contract is None:
            blockers.append("current_futures_contract_missing")
        if (
            primary_source_id == NINJATRADER_MARKET_SOURCE_ID
            or fallback_source_id == NINJATRADER_MARKET_SOURCE_ID
        ) and binding.market_data_contract_id is None:
            blockers.append("market_data_contract_id_missing")
        if binding.expiry_utc is None:
            blockers.append("futures_expiry_missing")
        if next_contract is None:
            blockers.append("next_futures_contract_missing")
        if (
            broker_symbol is not None
            and current_contract is not None
            and broker_symbol != current_contract
        ):
            blockers.append("futures_broker_symbol_contract_mismatch")
        if (
            as_of_utc is not None
            and binding.expiry_utc is not None
        ):
            if as_of_utc.tzinfo is None:
                raise ValueError("as_of_utc must be timezone-aware")
            cutoff = binding.expiry_utc - timedelta(
                hours=base.futures_lifecycle.roll_cutoff_hours_before_expiry
            )
            if as_of_utc >= cutoff:
                blockers.append("futures_contract_in_roll_cutoff")
    elif any(
        value is not None
        for value in (
            _clean(binding.current_contract),
            binding.market_data_contract_id,
            binding.expiry_utc,
            _clean(binding.next_contract),
        )
    ):
        blockers.append("non_futures_contract_fields_present")

    return tuple(dict.fromkeys(blockers))


def materialize_bound_registry_row(
    binding: RuntimeRegistryBinding,
    *,
    as_of_utc: datetime | None = None,
) -> ProductRegistryRow:
    blockers = binding_blockers(binding, as_of_utc=as_of_utc)
    if blockers:
        raise ValueError(
            "runtime registry binding incomplete: " + ",".join(blockers)
        )

    base = registry_row(binding.asset_id)
    row = replace(base, broker_symbol=str(binding.broker_symbol))
    row = bind_market_data(
        row,
        primary_source_id=str(binding.primary_market_source_id),
        stale_threshold_ms=int(binding.stale_threshold_ms),
        fallback_source_id=binding.fallback_market_source_id,
    )
    if row.futures_lifecycle is not None:
        assert binding.expiry_utc is not None
        row = bind_futures_contract(
            row,
            current_contract=str(binding.current_contract),
            expiry_utc=binding.expiry_utc,
            next_contract=str(binding.next_contract),
        )

    errors = validate_registry_row(row)
    if errors:
        raise ValueError("runtime registry row invalid: " + ",".join(errors))
    if not row.market_data_ready():
        raise ValueError("runtime registry row market data is not ready")
    if as_of_utc is not None and not row.lifecycle_fire_eligible(as_of_utc):
        raise ValueError("runtime registry row lifecycle is not FIRE-eligible")
    return row
