"""Canonical AETHER Pre-Code Freeze v1.0 contract.

This module is specification authority encoded as data. It deliberately imports
nothing from the legacy `app.*` runtime.

Source authority:
- AETHER Firm Master Blueprint v5.0
- AETHER Playbook Pack v1.4 FULL
- AETHER Pre-Code Freeze v1.0
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Final


FREEZE_VERSION: Final = "AETHER-PRECODE-1.0"
SPEC_BUNDLE: Final = "firm-v5.0+playbook-v1.4+precode-v1.0"

SOURCE_FINGERPRINTS: Final = MappingProxyType(
    {
        "AETHER_Firm_Master_Blueprint_v5.pdf":
            "a50652acb4fc5ea08b5c5a80fcb4d95fbe33904ca727c1429e53498e066055b4",
        "AETHER_v1.4_FULL.pdf":
            "c6dd561f2f8760fce1565ec9b9c87794445517f32fb54f4e258964e310926cf4",
        "AETHER_MASTER_FULL_v5_PLUS_PLAYBOOK_v1.4.pdf":
            "59a370a3c287cd3310cbf80231b63bb257ba15b64d9e889556711626347ddb51",
    }
)


class ResearchState(StrEnum):
    HYPOTHESIS = "HYPOTHESIS"
    SPEC = "SPEC"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


class EvidenceState(StrEnum):
    CANDIDATE = "CANDIDATE"
    EVIDENCE_ACCUMULATING = "EVIDENCE_ACCUMULATING"
    KEEP_PROBATION = "KEEP_PROBATION"
    KEEP_TRUSTED = "KEEP_TRUSTED"
    CUT_SIZE = "CUT_SIZE"
    BENCH = "BENCH"


class OperationalState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class GovernorState(StrEnum):
    NORMAL = "NORMAL"
    HALT = "HALT"


class FirmEvidenceState(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    FIRM_VALIDATED = "FIRM_VALIDATED"


@dataclass(frozen=True, slots=True)
class ProductSideSpec:
    asset_id: str
    display_identity: str
    venue_product: str
    long_supported: bool
    short_supported: bool
    short_requires_locate: bool = False
    executable_contract_family: str | None = None
    max_contracts: int | None = None
    note: str = ""


_PRODUCT_SPECS = {
    "btc": ProductSideSpec(
        asset_id="btc",
        display_identity="BTC",
        venue_product="Kraken spot crypto",
        long_supported=True,
        short_supported=False,
        note=(
            "Family A long daily_swing eligible; failed-break short definition "
            "preserved but operationally DISABLED."
        ),
    ),
    "eth": ProductSideSpec(
        asset_id="eth",
        display_identity="ETH",
        venue_product="Kraken spot crypto",
        long_supported=True,
        short_supported=False,
        note=(
            "Family A long + BTC rider eligible; failed-break short definition "
            "preserved but operationally DISABLED."
        ),
    ),
    "eurusd": ProductSideSpec(
        asset_id="eurusd",
        display_identity="EURUSD",
        venue_product="tastyfx FX",
        long_supported=True,
        short_supported=True,
        note=(
            "Scalp BENCH; intraday/swing Family A; failed-break intraday/swing; "
            "range-harvest EURUSD only."
        ),
    ),
    "usdjpy": ProductSideSpec(
        asset_id="usdjpy",
        display_identity="USDJPY",
        venue_product="tastyfx FX",
        long_supported=True,
        short_supported=True,
        note=(
            "Scalp BENCH; intraday/swing Family A; failed-break intraday/swing; "
            "OUT of Family C range v1.3."
        ),
    ),
    "mes": ProductSideSpec(
        asset_id="mes",
        display_identity="MES",
        venue_product="Ninja micro future",
        long_supported=True,
        short_supported=True,
        max_contracts=1,
        note="Family A scalp/intraday/swing; failed-break intraday.",
    ),
    "mnq": ProductSideSpec(
        asset_id="mnq",
        display_identity="MNQ",
        venue_product="Ninja micro future",
        long_supported=True,
        short_supported=True,
        max_contracts=1,
        note="Family A scalp/intraday/swing; failed-break intraday.",
    ),
    "mgc": ProductSideSpec(
        asset_id="mgc",
        display_identity="MGC",
        venue_product="Ninja micro future",
        long_supported=True,
        short_supported=True,
        max_contracts=1,
        note="Family A intraday/swing; failed-break intraday.",
    ),
    "mcl": ProductSideSpec(
        asset_id="mcl",
        display_identity="MCL",
        venue_product="Ninja micro future",
        long_supported=True,
        short_supported=True,
        max_contracts=1,
        note="Family A intraday/swing; failed-break intraday.",
    ),
    "us10y": ProductSideSpec(
        asset_id="us10y",
        display_identity="US10Y / ZN",
        venue_product="Ninja Treasury future",
        long_supported=True,
        short_supported=True,
        executable_contract_family="ZN",
        max_contracts=1,
        note=(
            "Family A swing + failed-break swing. Execution uses ZN price/tick "
            "mechanics; continuous/yield series are research_only."
        ),
    ),
    "nvda": ProductSideSpec(
        asset_id="nvda",
        display_identity="NVDA",
        venue_product="IBKR equity",
        long_supported=True,
        short_supported=True,
        short_requires_locate=True,
        note=(
            "Family A scalp/intraday/swing; failed-break intraday; "
            "range-harvest NVDA only."
        ),
    ),
    "tsla": ProductSideSpec(
        asset_id="tsla",
        display_identity="TSLA",
        venue_product="IBKR equity",
        long_supported=True,
        short_supported=True,
        short_requires_locate=True,
        note=(
            "Family A scalp/intraday/swing; failed-break intraday; "
            "OUT of Family C range v1.3."
        ),
    ),
    "pltr": ProductSideSpec(
        asset_id="pltr",
        display_identity="PLTR",
        venue_product="IBKR equity",
        long_supported=True,
        short_supported=True,
        short_requires_locate=True,
        note=(
            "Family A scalp/intraday/swing; failed-break intraday; "
            "OUT of Family C range v1.3."
        ),
    ),
}

PRODUCT_SPECS: Final = MappingProxyType(_PRODUCT_SPECS)

CRYPTO_SHORT_DISABLED_PLAYBOOKS: Final = frozenset(
    {"pb_crypto_failed_break_v1_3", "pb_eth_failed_break_v1_3"}
)

# Firm risk policy defaults. Hard constitutional ceilings remain source-controlled.
TRADE_RISK_FRACTION: Final = 0.0075
ASSET_RISK_FRACTION: Final = 0.0150
CLUSTER_RISK_FRACTION: Final = 0.0225
PORTFOLIO_RISK_FRACTION: Final = 0.0300
EMERGENCY_MAX_OPEN_DEFAULT: Final = 4
EMERGENCY_MAX_OPEN_HARD: Final = 6

# F-004: execution identity for AETHER asset_id=us10y.
US10Y_EXECUTABLE_FAMILY: Final = "ZN"
US10Y_TICK_POINTS: Final = 1 / 64
US10Y_TICK_VALUE_USD: Final = 15.625
US10Y_LEGACY_YIELD_EXECUTION_MATH_ALLOWED: Final = False

# F-005: Portfolio Allocator v1 is sequencing only.
ALLOCATOR_VERSION: Final = "allocation_score_v1"
ALLOCATOR_WEIGHTS: Final = MappingProxyType(
    {
        "ros_norm": 0.45,
        "conservative_expectancy_score": 0.20,
        "evidence_quality_score": 0.15,
        "diversification_score": 0.10,
        "execution_quality_score": 0.10,
    }
)

EVIDENCE_QUALITY_SCORES: Final = MappingProxyType(
    {
        EvidenceState.KEEP_TRUSTED.value: 100,
        EvidenceState.KEEP_PROBATION.value: 80,
        EvidenceState.EVIDENCE_ACCUMULATING.value: 60,
        EvidenceState.CANDIDATE.value: 50,
        EvidenceState.CUT_SIZE.value: 20,
        EvidenceState.BENCH.value: 0,
    }
)

PAPER_ONLY: Final = True
LIVE_BLOCKED: Final = True
FORCED_ENTRIES_STRATEGY_TEST: Final = False
FORCED_ENTRIES_EXECUTION_VALIDATION_ONLY: Final = True


def product_spec(asset_id: str) -> ProductSideSpec:
    return PRODUCT_SPECS[str(asset_id).strip().lower()]


def side_supported(asset_id: str, side: str, *, locate_ok: bool = False) -> bool:
    spec = product_spec(asset_id)
    normalized = str(side).strip().lower()
    if normalized == "long":
        return spec.long_supported
    if normalized == "short":
        if not spec.short_supported:
            return False
        if spec.short_requires_locate and not locate_ok:
            return False
        return True
    return False


def effective_route_eligible(
    *,
    research_state: ResearchState,
    evidence_state: EvidenceState,
    operational_state: OperationalState,
    governor_state: GovernorState,
    asset_id: str,
    side: str,
    market_healthy: bool,
    session_eligible: bool,
    locate_ok: bool = False,
) -> bool:
    """Frozen F-002 eligibility law, excluding later strategy-specific gates."""
    return (
        research_state is ResearchState.FROZEN
        and evidence_state is not EvidenceState.BENCH
        and operational_state is OperationalState.ENABLED
        and governor_state is GovernorState.NORMAL
        and side_supported(asset_id, side, locate_ok=locate_ok)
        and bool(market_healthy)
        and bool(session_eligible)
    )


def canonical_freeze_payload() -> dict[str, object]:
    """Return JSON-safe inputs whose material change requires a new freeze/hash."""
    return {
        "freeze_version": FREEZE_VERSION,
        "spec_bundle": SPEC_BUNDLE,
        "source_fingerprints": dict(SOURCE_FINGERPRINTS),
        "states": {
            "research_state": [x.value for x in ResearchState],
            "evidence_state": [x.value for x in EvidenceState],
            "operational_state": [x.value for x in OperationalState],
            "governor_state": [x.value for x in GovernorState],
            "firm_evidence_state": [x.value for x in FirmEvidenceState],
        },
        "products": {
            asset_id: asdict(spec)
            for asset_id, spec in sorted(PRODUCT_SPECS.items())
        },
        "crypto_short_disabled_playbooks": sorted(CRYPTO_SHORT_DISABLED_PLAYBOOKS),
        "risk_defaults": {
            "trade": TRADE_RISK_FRACTION,
            "asset": ASSET_RISK_FRACTION,
            "cluster": CLUSTER_RISK_FRACTION,
            "portfolio": PORTFOLIO_RISK_FRACTION,
            "emergency_max_open_default": EMERGENCY_MAX_OPEN_DEFAULT,
            "emergency_max_open_hard": EMERGENCY_MAX_OPEN_HARD,
        },
        "us10y": {
            "asset_id": "us10y",
            "executable_contract_family": US10Y_EXECUTABLE_FAMILY,
            "tick_points": US10Y_TICK_POINTS,
            "tick_value_usd": US10Y_TICK_VALUE_USD,
            "legacy_yield_execution_math_allowed":
                US10Y_LEGACY_YIELD_EXECUTION_MATH_ALLOWED,
        },
        "allocator": {
            "version": ALLOCATOR_VERSION,
            "weights": dict(ALLOCATOR_WEIGHTS),
            "evidence_quality_scores": dict(EVIDENCE_QUALITY_SCORES),
            "sequencing_only": True,
            "may_write_quantity": False,
            "may_expand_risk": False,
        },
        "safety": {
            "paper_only": PAPER_ONLY,
            "live_blocked": LIVE_BLOCKED,
            "forced_entries_strategy_test": FORCED_ENTRIES_STRATEGY_TEST,
            "forced_entries_execution_validation_only":
                FORCED_ENTRIES_EXECUTION_VALIDATION_ONLY,
        },
    }


def configuration_hash() -> str:
    raw = json.dumps(
        canonical_freeze_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


CONFIGURATION_HASH: Final = configuration_hash()
