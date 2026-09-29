"""Read-only Alpha Factory research-integrity diagnostics.

The AETHER source requires the Alpha Factory to detect parameter mining, sample
starvation, outlier dependence, and regime concentration while preserving sample
domain separation and independent-n integrity. The source does not bind universal
numeric thresholds for those four diagnostics, so this module accepts optional
versioned policy thresholds and reports unbound rules instead of inventing them.

This module has no promotion, Risk, Governor, or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from aether_vnext.research import EvidenceWindow


@dataclass(frozen=True, slots=True)
class ResearchIntegrityTrade:
    trade_id: str
    episode_id: str
    sample_domain: str
    net_pnl_usd: float
    regime_label: str

    def __post_init__(self) -> None:
        for name in ("trade_id", "episode_id", "sample_domain", "regime_label"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if self.sample_domain not in EvidenceWindow.VALID_SAMPLE_DOMAINS:
            raise ValueError(f"invalid sample_domain: {self.sample_domain}")
        if isinstance(self.net_pnl_usd, bool):
            raise ValueError("net_pnl_usd must be numeric, not boolean")
        if not math.isfinite(float(self.net_pnl_usd)):
            raise ValueError("net_pnl_usd must be finite")


@dataclass(frozen=True, slots=True)
class ResearchIntegrityPolicy:
    """Optional versioned thresholds supplied by policy/source authority."""

    minimum_independent_n: int | None = None
    max_parameter_variants: int | None = None
    max_largest_trade_share: float | None = None
    max_top_decile_trade_share: float | None = None
    max_regime_share: float | None = None

    def __post_init__(self) -> None:
        for name in ("minimum_independent_n", "max_parameter_variants"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer when bound")
        for name in (
            "max_largest_trade_share",
            "max_top_decile_trade_share",
            "max_regime_share",
        ):
            value = getattr(self, name)
            if value is not None and isinstance(value, bool):
                raise ValueError(f"{name} must be numeric, not boolean")
            if value is not None and (
                not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"{name} must be in [0,1] when bound")


@dataclass(frozen=True, slots=True)
class ResearchIntegrityAssessment:
    sample_domain: str | None
    trade_count: int
    independent_n: int
    parameter_variant_count: int
    largest_trade_share_of_positive_pnl: float | None
    top_decile_share_of_positive_pnl: float | None
    max_regime_trade_share: float | None
    flags: tuple[str, ...]
    unresolved_rules: tuple[str, ...]
    status: str


def _positive_pnl_concentration(
    rows: tuple[ResearchIntegrityTrade, ...],
) -> tuple[float | None, float | None]:
    positive = sorted(
        (float(row.net_pnl_usd) for row in rows if row.net_pnl_usd > 0.0),
        reverse=True,
    )
    total_positive = sum(positive)
    if not positive or total_positive <= 0.0:
        return None, None
    largest = positive[0] / total_positive
    top_n = max(1, math.ceil(len(rows) * 0.10))
    top_decile = sum(positive[:top_n]) / total_positive
    return largest, top_decile


def _max_regime_share(
    rows: tuple[ResearchIntegrityTrade, ...],
) -> float | None:
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.regime_label] = counts.get(row.regime_label, 0) + 1
    return max(counts.values()) / len(rows)


def assess_research_integrity(
    trades: Iterable[ResearchIntegrityTrade],
    *,
    parameter_variant_count: int,
    policy: ResearchIntegrityPolicy | None = None,
) -> ResearchIntegrityAssessment:
    """Measure source-required Alpha Factory integrity risks without promotion authority."""
    rows = tuple(trades)
    if (
        not isinstance(parameter_variant_count, int)
        or isinstance(parameter_variant_count, bool)
        or parameter_variant_count < 0
    ):
        raise ValueError("parameter_variant_count must be a nonnegative integer")

    trade_ids = [row.trade_id for row in rows]
    if len(trade_ids) != len(set(trade_ids)):
        raise ValueError("duplicate trade_id in research integrity sample")

    domains = {row.sample_domain for row in rows}
    if len(domains) > 1:
        raise ValueError("research integrity samples cannot mix sample domains")
    sample_domain = next(iter(domains), None)

    independent_n = len({row.episode_id for row in rows})
    largest_share, top_decile_share = _positive_pnl_concentration(rows)
    regime_share = _max_regime_share(rows)

    bound = policy or ResearchIntegrityPolicy()
    flags: list[str] = []
    unresolved: list[str] = []

    if bound.max_parameter_variants is None:
        unresolved.append("parameter_mining_threshold_unbound")
    elif parameter_variant_count > bound.max_parameter_variants:
        flags.append("parameter_mining")

    if bound.minimum_independent_n is None:
        unresolved.append("sample_starvation_threshold_unbound")
    elif independent_n < bound.minimum_independent_n:
        flags.append("sample_starvation")

    outlier_policy_bound = (
        bound.max_largest_trade_share is not None
        and bound.max_top_decile_trade_share is not None
    )
    if not outlier_policy_bound:
        unresolved.append("outlier_dependence_threshold_unbound")
    elif largest_share is not None and top_decile_share is not None:
        if (
            largest_share > float(bound.max_largest_trade_share)
            or top_decile_share > float(bound.max_top_decile_trade_share)
        ):
            flags.append("outlier_dependence")

    if bound.max_regime_share is None:
        unresolved.append("regime_concentration_threshold_unbound")
    elif regime_share is not None and regime_share > float(bound.max_regime_share):
        flags.append("regime_concentration")

    if flags:
        status = "FLAGGED"
    elif unresolved:
        status = "UNBOUND_POLICY"
    else:
        status = "CLEAR"

    return ResearchIntegrityAssessment(
        sample_domain=sample_domain,
        trade_count=len(rows),
        independent_n=independent_n,
        parameter_variant_count=parameter_variant_count,
        largest_trade_share_of_positive_pnl=largest_share,
        top_decile_share_of_positive_pnl=top_decile_share,
        max_regime_trade_share=regime_share,
        flags=tuple(flags),
        unresolved_rules=tuple(unresolved),
        status=status,
    )
