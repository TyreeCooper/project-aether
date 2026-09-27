"""Indicator-calculation authority for AETHER vNext.

The Playbook Pack names EMA, ATR, and realized-volatility inputs but does not bind
all numerical conventions needed for deterministic replay. AETHER must not silently
choose a library/default convention at runtime.

This registry is intentionally separate from the indicator implementation itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Iterable


@dataclass(frozen=True, slots=True)
class IndicatorAuthority:
    indicator_id: str
    source_bound: bool
    blocker_code: str | None
    source_requirement: str

    def __post_init__(self) -> None:
        if not str(self.indicator_id).strip():
            raise ValueError("indicator_id is required")
        if not str(self.source_requirement).strip():
            raise ValueError("source_requirement is required")
        if self.source_bound and self.blocker_code is not None:
            raise ValueError("source-bound indicator cannot carry blocker_code")
        if not self.source_bound and not str(self.blocker_code or "").strip():
            raise ValueError("unbound indicator requires blocker_code")


INDICATOR_AUTHORITIES: Final = MappingProxyType(
    {
        "ema": IndicatorAuthority(
            indicator_id="ema",
            source_bound=False,
            blocker_code="ema_calculation_convention_unbound",
            source_requirement=(
                "EMA20/EMA50 are required by playbooks, but runtime seed/"
                "initialization and smoothing convention are not frozen."
            ),
        ),
        "atr": IndicatorAuthority(
            indicator_id="atr",
            source_bound=False,
            blocker_code="atr_calculation_convention_unbound",
            source_requirement=(
                "ATR(14) is required by playbooks, but smoothing/initialization "
                "convention is not frozen."
            ),
        ),
        "realized_vol": IndicatorAuthority(
            indicator_id="realized_vol",
            source_bound=False,
            blocker_code="realized_vol_calculation_convention_unbound",
            source_requirement=(
                "realized_vol(trigger_interval,14) and prior-90-calendar-day "
                "percentile comparison are frozen, but the exact return/"
                "annualization convention is not."
            ),
        ),
        "prior_closed_bar_range": IndicatorAuthority(
            indicator_id="prior_closed_bar_range",
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "Prior-N calculations use CLOSED bars and exclude the current "
                "trigger/forming bar."
            ),
        ),
    }
)


def indicator_authority(indicator_id: str) -> IndicatorAuthority | None:
    return INDICATOR_AUTHORITIES.get(str(indicator_id).strip())


def indicator_authority_blockers(
    required_indicator_ids: Iterable[str],
) -> tuple[str, ...]:
    blockers: list[str] = []
    seen: set[str] = set()
    for raw_id in required_indicator_ids:
        indicator_id = str(raw_id).strip()
        if not indicator_id:
            raise ValueError("required indicator_id must be nonblank")
        if indicator_id in seen:
            continue
        seen.add(indicator_id)

        authority = indicator_authority(indicator_id)
        if authority is None:
            blockers.append("indicator_authority_unknown:" + indicator_id)
            continue
        if not authority.source_bound:
            assert authority.blocker_code is not None
            blockers.append(authority.blocker_code)
    return tuple(blockers)
