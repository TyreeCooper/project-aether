"""Frozen AETHER vNext Playbook Pack v1.4 runtime registry.

This module carries only source-bound playbook identity and dispatch metadata.
It does not implement Scout signal logic, does not import legacy strategies, and
does not promote CANDIDATE evidence state to KEEP.

Source authority:
- AETHER Playbook Pack v1.4 FULL (v1.3 FULL executable definitions + Part C)
- AETHER Pre-Code Freeze v1.0 operational overrides
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Iterable

from aether_vnext.freeze import (
    CRYPTO_SHORT_DISABLED_PLAYBOOKS,
    EvidenceState,
    OperationalState,
    ResearchState,
)


class PlaybookFamily(StrEnum):
    A = "A"
    B = "B"
    C = "C"


_FAMILY_PRECEDENCE: Final = MappingProxyType(
    {
        PlaybookFamily.A: 1,
        PlaybookFamily.B: 2,
        PlaybookFamily.C: 3,
    }
)


_INTERVALS: Final = MappingProxyType(
    {
        "1m": timedelta(minutes=1),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
    }
)


SEED_ASSET_CLUSTERS: Final = MappingProxyType(
    {
        "btc": "crypto",
        "eth": "crypto",
        "eurusd": "fx",
        "usdjpy": "fx",
        "mes": "us_beta",
        "mnq": "us_beta",
        "mgc": "metal",
        "mcl": "energy",
        "us10y": "rates",
        "nvda": "us_beta",
        "tsla": "us_beta",
        "pltr": "us_beta",
    }
)

# Source-bound cross-asset Risk attribution. This is not directional netting.
# ETH rider definitions consume their own ETH asset risk and additionally
# attribute 50% of initial stop-risk to the BTC asset cap.
_PLAYBOOK_ASSET_RISK_HITCHES: Final = {
    "pb_eth_rider_v1_2": MappingProxyType({"btc": 0.50}),
    "pb_eth_failed_break_v1_3": MappingProxyType({"btc": 0.50}),
}
PLAYBOOK_ASSET_RISK_HITCHES: Final = MappingProxyType(
    _PLAYBOOK_ASSET_RISK_HITCHES
)


def cluster_for_asset(asset_id: str) -> str:
    try:
        return str(SEED_ASSET_CLUSTERS[str(asset_id)])
    except KeyError as exc:
        raise KeyError(f"unknown canonical cluster for asset: {asset_id}") from exc


def cluster_for_playbook(playbook_id: str) -> str:
    spec = playbook(playbook_id)
    clusters = {cluster_for_asset(asset) for asset in spec.allowed_assets}
    if len(clusters) != 1:
        raise RuntimeError(
            f"playbook spans multiple canonical clusters: {playbook_id}"
        )
    return next(iter(clusters))


def asset_risk_hitches(playbook_id: str) -> MappingProxyType:
    playbook(playbook_id)
    mapping = PLAYBOOK_ASSET_RISK_HITCHES.get(str(playbook_id))
    if mapping is None:
        return MappingProxyType({})
    return mapping


@dataclass(frozen=True, slots=True)
class PlaybookSpec:
    playbook_id: str
    version: str
    family: PlaybookFamily
    mechanism_class: str
    allowed_assets: tuple[str, ...]
    allowed_sides: tuple[str, ...]
    horizon: str
    trigger_interval_label: str
    evidence_state: EvidenceState
    research_state: ResearchState = ResearchState.FROZEN
    operational_state: OperationalState = OperationalState.ENABLED

    def __post_init__(self) -> None:
        if not self.playbook_id.startswith("pb_"):
            raise ValueError("playbook_id must use canonical pb_ prefix")
        if not self.version:
            raise ValueError("version is required")
        if not self.mechanism_class:
            raise ValueError("mechanism_class is required")
        if not self.allowed_assets:
            raise ValueError("allowed_assets cannot be empty")
        if not self.allowed_sides:
            raise ValueError("allowed_sides cannot be empty")
        if not self.horizon:
            raise ValueError("horizon is required")
        if self.trigger_interval_label not in _INTERVALS:
            raise ValueError("unsupported trigger interval")
        if len(set(self.allowed_assets)) != len(self.allowed_assets):
            raise ValueError("duplicate allowed asset")
        if len(set(self.allowed_sides)) != len(self.allowed_sides):
            raise ValueError("duplicate allowed side")
        if not set(self.allowed_sides) <= {"long", "short"}:
            raise ValueError("allowed_sides must be long/short")

    @property
    def trigger_interval(self) -> timedelta:
        return _INTERVALS[self.trigger_interval_label]

    @property
    def family_precedence(self) -> int:
        return int(_FAMILY_PRECEDENCE[self.family])

    @property
    def scout_definition_enabled(self) -> bool:
        """Definition-level gate only; not full route eligibility."""
        return (
            self.research_state is ResearchState.FROZEN
            and self.evidence_state is not EvidenceState.BENCH
            and self.operational_state is OperationalState.ENABLED
        )

    def route_tuples(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (asset_id, side, self.horizon)
            for asset_id in self.allowed_assets
            for side in self.allowed_sides
        )


def _spec(
    playbook_id: str,
    version: str,
    family: PlaybookFamily,
    mechanism_class: str,
    assets: tuple[str, ...],
    sides: tuple[str, ...],
    horizon: str,
    trigger: str,
    *,
    evidence: EvidenceState = EvidenceState.CANDIDATE,
) -> PlaybookSpec:
    operational = (
        OperationalState.DISABLED
        if playbook_id in CRYPTO_SHORT_DISABLED_PLAYBOOKS
        else OperationalState.ENABLED
    )
    return PlaybookSpec(
        playbook_id=playbook_id,
        version=version,
        family=family,
        mechanism_class=mechanism_class,
        allowed_assets=assets,
        allowed_sides=sides,
        horizon=horizon,
        trigger_interval_label=trigger,
        evidence_state=evidence,
        operational_state=operational,
    )


_PLAYBOOKS: Final = (
    # Family A — bound v1.2 definitions.
    _spec(
        "pb_crypto_swing_v1_2", "1.2", PlaybookFamily.A,
        "breakout_continuation", ("btc", "eth"), ("long",),
        "daily_swing", "1h",
    ),
    _spec(
        "pb_eth_rider_v1_2", "1.2", PlaybookFamily.A,
        "dependent_breakout_continuation", ("eth",), ("long",),
        "daily_swing", "1h",
    ),
    _spec(
        "pb_fx_intraday_v1_2", "1.2", PlaybookFamily.A,
        "session_structure_break", ("eurusd", "usdjpy"),
        ("long", "short"), "intraday", "15m",
    ),
    _spec(
        "pb_fx_swing_v1_2", "1.2", PlaybookFamily.A,
        "breakout_continuation", ("eurusd", "usdjpy"),
        ("long", "short"), "swing", "1h",
    ),
    _spec(
        "pb_fx_scalp_v1_2", "1.2", PlaybookFamily.A,
        "short_horizon_fx_break", ("eurusd", "usdjpy"),
        ("long", "short"), "scalp", "1m",
        evidence=EvidenceState.BENCH,
    ),
    _spec(
        "pb_idx_scalp_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("mes", "mnq"), ("long", "short"),
        "scalp", "15m",
    ),
    _spec(
        "pb_idx_intraday_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("mes", "mnq"), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_idx_swing_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("mes", "mnq"), ("long", "short"),
        "swing", "15m",
    ),
    _spec(
        "pb_metal_intraday_v1_2", "1.2", PlaybookFamily.A,
        "session_structure_break", ("mgc",), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_metal_swing_v1_2", "1.2", PlaybookFamily.A,
        "session_structure_break", ("mgc",), ("long", "short"),
        "swing", "15m",
    ),
    _spec(
        "pb_energy_intraday_v1_2", "1.2", PlaybookFamily.A,
        "session_structure_break", ("mcl",), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_energy_swing_v1_2", "1.2", PlaybookFamily.A,
        "session_structure_break", ("mcl",), ("long", "short"),
        "swing", "15m",
    ),
    _spec(
        "pb_rates_swing_v1_2", "1.2", PlaybookFamily.A,
        "breakout_continuation", ("us10y",), ("long", "short"),
        "swing", "1h",
    ),
    _spec(
        "pb_eq_scalp_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("nvda", "tsla", "pltr"),
        ("long", "short"), "scalp", "15m",
    ),
    _spec(
        "pb_eq_intraday_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("nvda", "tsla", "pltr"),
        ("long", "short"), "intraday", "15m",
    ),
    _spec(
        "pb_eq_swing_v1_2", "1.2", PlaybookFamily.A,
        "prior_day_range_break", ("nvda", "tsla", "pltr"),
        ("long", "short"), "swing", "15m",
    ),

    # Family B — v1.3 failed-break fade definitions.
    _spec(
        "pb_crypto_failed_break_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("btc",), ("short",),
        "daily_swing", "1h",
    ),
    _spec(
        "pb_eth_failed_break_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("eth",), ("short",),
        "daily_swing", "1h",
    ),
    _spec(
        "pb_fx_failed_session_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("eurusd", "usdjpy"), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_fx_failed_swing_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("eurusd", "usdjpy"), ("long", "short"),
        "swing", "1h",
    ),
    _spec(
        "pb_idx_failed_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("mes", "mnq"), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_metal_failed_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("mgc",), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_energy_failed_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("mcl",), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_rates_failed_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("us10y",), ("long", "short"),
        "swing", "1h",
    ),
    _spec(
        "pb_eq_failed_v1_3", "1.3", PlaybookFamily.B,
        "failed_break_fade", ("nvda", "tsla", "pltr"),
        ("long", "short"), "intraday", "15m",
    ),

    # Family C — v1.3 range-harvest definitions.
    _spec(
        "pb_fx_range_v1_3", "1.3", PlaybookFamily.C,
        "range_mean_reversion", ("eurusd",), ("long", "short"),
        "intraday", "15m",
    ),
    _spec(
        "pb_eq_range_v1_3", "1.3", PlaybookFamily.C,
        "range_mean_reversion", ("nvda",), ("long", "short"),
        "intraday", "15m",
    ),
)


PLAYBOOK_REGISTRY: Final = MappingProxyType(
    {spec.playbook_id: spec for spec in _PLAYBOOKS}
)


def playbook(playbook_id: str) -> PlaybookSpec:
    try:
        return PLAYBOOK_REGISTRY[str(playbook_id)]
    except KeyError as exc:
        raise KeyError(f"unknown playbook_id: {playbook_id}") from exc


def ordered_playbooks(
    specs: Iterable[PlaybookSpec] | None = None,
) -> tuple[PlaybookSpec, ...]:
    rows = tuple(PLAYBOOK_REGISTRY.values()) if specs is None else tuple(specs)
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.family_precedence,
                row.playbook_id,
            ),
        )
    )


def playbooks_for(
    *,
    asset_id: str,
    horizon: str | None = None,
    side: str | None = None,
    include_benched: bool = False,
    include_operationally_disabled: bool = False,
) -> tuple[PlaybookSpec, ...]:
    rows: list[PlaybookSpec] = []
    for spec in PLAYBOOK_REGISTRY.values():
        if asset_id not in spec.allowed_assets:
            continue
        if horizon is not None and spec.horizon != horizon:
            continue
        if side is not None and side not in spec.allowed_sides:
            continue
        if not include_benched and spec.evidence_state is EvidenceState.BENCH:
            continue
        if (
            not include_operationally_disabled
            and spec.operational_state is OperationalState.DISABLED
        ):
            continue
        rows.append(spec)
    return ordered_playbooks(rows)


def canonical_playbook_ids() -> tuple[str, ...]:
    return tuple(spec.playbook_id for spec in ordered_playbooks())
