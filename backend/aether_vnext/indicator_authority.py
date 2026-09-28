"""Indicator-calculation authority for AETHER vNext.

The frozen Master/Playbook source set names EMA20/EMA50, ATR14, and realized
volatility without binding every numerical convention. AETHER Indicator Convention
v1 is the operator-approved specification decision that closes those calculation
gaps without rewriting the historical source documents.
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
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "AETHER Indicator Convention v1: EMA20/EMA50 use completed "
                "bar closes, SMA(N) initialization, then alpha=2/(N+1)."
            ),
        ),
        "atr": IndicatorAuthority(
            indicator_id="atr",
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "AETHER Indicator Convention v1: ATR14 uses standard true "
                "range, a 14-TR arithmetic seed, then Wilder smoothing."
            ),
        ),
        "realized_vol": IndicatorAuthority(
            indicator_id="realized_vol",
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "AETHER Indicator Convention v1: realized_vol14 uses the "
                "trailing 14 completed-bar log returns as sqrt(sum(r^2)) "
                "with no annualization."
            ),
        ),
        "volatility_percentile": IndicatorAuthority(
            indicator_id="volatility_percentile",
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "AETHER Volatility Percentile Convention v1: current RV14 "
                "is ranked against PIT RV14 observations at completed "
                "same-interval closes in [T-90d,T) using empirical midrank "
                "with no interpolation."
            ),
        ),
        "prior_closed_bar_range": IndicatorAuthority(
            indicator_id="prior_closed_bar_range",
            source_bound=True,
            blocker_code=None,
            source_requirement=(
                "Playbook Pack: prior-N calculations use CLOSED bars and "
                "exclude the current trigger/forming bar."
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
