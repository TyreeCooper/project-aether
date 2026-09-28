"""Research-only closed-bar replay orchestration for AETHER vNext.

This module evaluates immutable PIT research features through the frozen Family A/B/C
evaluators and the existing deterministic same-bar precedence engine.

It deliberately bypasses runtime_cycle because immutable research bars do not and
must not fabricate live exchange-print timestamps. No Setup/Ticket, Risk, fill,
database, or campaign mutation occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aether_vnext.family_a import FamilyAEvaluation
from aether_vnext.family_b import FamilyBEvaluation
from aether_vnext.family_c import FamilyCEvaluation
from aether_vnext.playbook_engine import (
    ClosedBarRuntimeDecision,
    resolve_closed_bar_runtime,
)
from aether_vnext.playbook_trend_features import (
    PlaybookTrendFeatureSnapshot,
)
from aether_vnext.playbooks import playbook
from aether_vnext.replay_family_adapter import (
    FamilyAReplayExtras,
    FamilyBReplayState,
    FamilyCReplayExtras,
    evaluate_replay_family_a,
    evaluate_replay_family_b,
    evaluate_replay_family_c,
)
from aether_vnext.replay_trend_adapter import (
    family_a_extras_from_trend_snapshot,
)
from aether_vnext.research_replay_features import (
    ResearchRegimeReadyFeatures,
)


def _canonical_request_text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchFamilyARequest:
    playbook_id: str
    side: str
    extras: FamilyAReplayExtras | None = None
    trend: PlaybookTrendFeatureSnapshot | None = None

    def __post_init__(self) -> None:
        _canonical_request_text(self.playbook_id, "playbook_id")
        _canonical_request_text(self.side, "side")
        if self.trend is None or self.extras is None:
            return
        manual_trend = (
            self.extras.trend_ema20,
            self.extras.trend_ema50,
            self.extras.slope_ema20_current,
            self.extras.slope_ema20_previous,
        )
        if any(value is not None for value in manual_trend):
            raise ValueError(
                "reviewed trend snapshot cannot be combined with manual trend fields"
            )


@dataclass(frozen=True, slots=True)
class ResearchFamilyBRequest:
    playbook_id: str
    side: str
    state: FamilyBReplayState

    def __post_init__(self) -> None:
        _canonical_request_text(self.playbook_id, "playbook_id")
        _canonical_request_text(self.side, "side")


@dataclass(frozen=True, slots=True)
class ResearchFamilyCRequest:
    playbook_id: str
    side: str
    extras: FamilyCReplayExtras | None = None

    def __post_init__(self) -> None:
        _canonical_request_text(self.playbook_id, "playbook_id")
        _canonical_request_text(self.side, "side")


@dataclass(frozen=True, slots=True)
class ResearchClosedBarInput:
    asset_id: str
    horizon: str
    features: ResearchRegimeReadyFeatures
    family_a: tuple[ResearchFamilyARequest, ...] = ()
    family_b: tuple[ResearchFamilyBRequest, ...] = ()
    family_c: tuple[ResearchFamilyCRequest, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.asset_id, str)
            or not self.asset_id
            or self.asset_id != self.asset_id.strip()
            or self.asset_id != self.asset_id.lower()
        ):
            raise ValueError("asset_id must be a canonical lowercase ID")
        if (
            not isinstance(self.horizon, str)
            or not self.horizon
            or self.horizon != self.horizon.strip()
        ):
            raise ValueError("horizon must be canonical text")
        if self.features.numerical.asset_id != self.asset_id:
            raise ValueError("research feature asset mismatch")
        _reject_duplicates(self.family_a, "Family-A")
        _reject_duplicates(self.family_b, "Family-B")
        _reject_duplicates(self.family_c, "Family-C")


@dataclass(frozen=True, slots=True)
class ResearchClosedBarResult:
    asset_id: str
    horizon: str
    trigger_research_bar_id: str
    trigger_bar_open_utc: datetime
    trigger_bar_close_utc: datetime
    decision: ClosedBarRuntimeDecision


def _reject_duplicates(rows: tuple[object, ...], label: str) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (
            str(getattr(row, "playbook_id")),
            str(getattr(row, "side")),
        )
        if key in seen:
            raise ValueError(f"duplicate {label} research replay request: {key}")
        seen.add(key)


def evaluate_research_closed_bar(
    cycle: ResearchClosedBarInput,
) -> ResearchClosedBarResult:
    """Evaluate one immutable PIT research trigger through A -> B -> C precedence."""
    a_rows: list[FamilyAEvaluation] = []
    for row in cycle.family_a:
        spec = playbook(row.playbook_id)
        extras = row.extras
        if row.trend is not None:
            dependency = row.extras or FamilyAReplayExtras()
            extras = family_a_extras_from_trend_snapshot(
                spec,
                asset_id=cycle.asset_id,
                features=cycle.features,
                trend=row.trend,
                btc_daily_close=dependency.btc_daily_close,
                btc_daily_ema50=dependency.btc_daily_ema50,
                btc_parent_watch_or_open_long=(
                    dependency.btc_parent_watch_or_open_long
                ),
                btc_parent_market_regime_eligible=(
                    dependency.btc_parent_market_regime_eligible
                ),
            )
        a_rows.append(
            evaluate_replay_family_a(
                spec,
                asset_id=cycle.asset_id,
                side=row.side,
                features=cycle.features,
                extras=extras,
            )
        )
    a: tuple[FamilyAEvaluation, ...] = tuple(a_rows)
    b: tuple[FamilyBEvaluation, ...] = tuple(
        evaluate_replay_family_b(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            state=row.state,
        )
        for row in cycle.family_b
    )
    c: tuple[FamilyCEvaluation, ...] = tuple(
        evaluate_replay_family_c(
            playbook(row.playbook_id),
            asset_id=cycle.asset_id,
            side=row.side,
            features=cycle.features,
            extras=row.extras,
        )
        for row in cycle.family_c
    )

    decision = resolve_closed_bar_runtime(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        family_a=a,
        family_b=b,
        family_c=c,
    )
    trigger = cycle.features.numerical.trigger_bar
    return ResearchClosedBarResult(
        asset_id=cycle.asset_id,
        horizon=cycle.horizon,
        trigger_research_bar_id=trigger.research_bar_id,
        trigger_bar_open_utc=trigger.bucket_open_utc,
        trigger_bar_close_utc=trigger.bucket_close_utc,
        decision=decision,
    )
