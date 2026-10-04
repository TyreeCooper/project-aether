"""MF-13 market-specific policy and replayable reference-data contracts.

AETHER Market Fabric does not apply one generic market policy to every asset class.
Each enabled class declares its own session/reference requirements. Unbound facts stay
explicitly unqualified instead of being guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class MarketClass(StrEnum):
    CRYPTO = "crypto"
    EQUITIES = "equities"
    FUTURES = "futures"
    FX = "fx"
    RATES = "rates"
    OPTIONS = "options"


@dataclass(frozen=True, slots=True)
class MarketPolicy:
    policy_version: str
    market_class: MarketClass
    session_model: str
    requires_sequence: bool
    requires_reference_data: tuple[str, ...]
    witness_policy_bound: bool
    liveness_policy_bound: bool
    execution_route_required: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if not self.session_model.strip():
            raise ValueError("session_model is required")

    @property
    def operational(self) -> bool:
        return self.witness_policy_bound and self.liveness_policy_bound

    @property
    def blockers(self) -> tuple[str, ...]:
        out: list[str] = []
        if not self.witness_policy_bound:
            out.append("witness_policy_unbound")
        if not self.liveness_policy_bound:
            out.append("liveness_policy_unbound")
        return tuple(out)


@dataclass(frozen=True, slots=True)
class ReferenceDataEvent:
    event_id: str
    instrument_id: str
    market_class: MarketClass
    reference_version: str
    event_type: str
    effective_from: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "instrument_id",
            "reference_version",
            "event_type",
            "effective_from",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        object.__setattr__(
            self,
            "payload",
            MappingProxyType(dict(self.payload)),
        )


REQUIRED_REFERENCE_TYPES = MappingProxyType(
    {
        MarketClass.CRYPTO: frozenset({"instrument_definition"}),
        MarketClass.EQUITIES: frozenset(
            {
                "instrument_definition",
                "corporate_action",
                "symbol_change",
                "auction_halt_status",
                "trade_correction",
            }
        ),
        MarketClass.FUTURES: frozenset(
            {
                "instrument_definition",
                "contract_expiry",
                "roll_mapping",
                "trading_session",
                "trade_correction",
            }
        ),
        MarketClass.FX: frozenset(
            {
                "instrument_definition",
                "trading_session",
            }
        ),
        MarketClass.RATES: frozenset(
            {
                "instrument_definition",
                "contract_expiry",
                "roll_mapping",
                "trading_session",
            }
        ),
        MarketClass.OPTIONS: frozenset(
            {
                "instrument_definition",
                "expiry",
                "strike",
                "option_right",
                "underlying_reference",
                "corporate_action",
            }
        ),
    }
)


def validate_reference_coverage(
    *,
    policy: MarketPolicy,
    observed_event_types: set[str],
) -> tuple[bool, tuple[str, ...]]:
    required = set(policy.requires_reference_data)
    missing = tuple(sorted(required - set(observed_event_types)))
    return (not missing, missing)


def market_policy(
    *,
    policy_version: str,
    market_class: MarketClass,
    witness_policy_bound: bool,
    liveness_policy_bound: bool,
) -> MarketPolicy:
    if market_class is MarketClass.CRYPTO:
        session = "24x7"
        requires_sequence = False
    elif market_class in {MarketClass.EQUITIES, MarketClass.FUTURES, MarketClass.RATES}:
        session = "exchange_calendar"
        requires_sequence = True
    elif market_class is MarketClass.FX:
        session = "otc_week"
        requires_sequence = False
    else:
        session = "exchange_calendar"
        requires_sequence = True
    return MarketPolicy(
        policy_version=policy_version,
        market_class=market_class,
        session_model=session,
        requires_sequence=requires_sequence,
        requires_reference_data=tuple(
            sorted(REQUIRED_REFERENCE_TYPES[market_class])
        ),
        witness_policy_bound=witness_policy_bound,
        liveness_policy_bound=liveness_policy_bound,
    )
