"""Review-only portfolio, concentration, and path diagnostics.

These functions produce evidence. They do not mutate strategy state, Risk, Governor,
or execution. Where the Master requires a diagnostic but does not bind a numerical
policy (for example bootstrap sample threshold / iteration / seed policy), the result
explicitly reports that policy as unresolved instead of fabricating one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
import math
from typing import Iterable

from aether_vnext.freeze import PORTFOLIO_RISK_FRACTION


@dataclass(frozen=True, slots=True)
class PathTrade:
    trade_id: str
    closed_at_utc: datetime
    net_pnl_usd: float
    initial_stop_risk_usd: float

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id is required")
        if self.closed_at_utc.tzinfo is None:
            raise ValueError("closed_at_utc must be timezone-aware")
        if not math.isfinite(float(self.net_pnl_usd)):
            raise ValueError("net_pnl_usd must be finite")
        if (
            not math.isfinite(float(self.initial_stop_risk_usd))
            or float(self.initial_stop_risk_usd) <= 0.0
        ):
            raise ValueError("initial_stop_risk_usd must be positive")


@dataclass(frozen=True, slots=True)
class PathDiagnostics:
    n: int
    max_drawdown_usd: float
    longest_losing_streak: int
    max_recovery_duration_s: float
    sample_ends_underwater: bool
    worst_tail_loss_r: float
    resampled_path_stress_status: str
    resampled_path_stress_reason: str


def path_diagnostics(trades: Iterable[PathTrade]) -> PathDiagnostics:
    rows = tuple(sorted(trades, key=lambda row: (row.closed_at_utc, row.trade_id)))
    ids = [row.trade_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate trade_id in path sample")

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    losing_streak = 0
    max_losing_streak = 0
    underwater_start: datetime | None = None
    max_recovery_s = 0.0
    worst_tail_r = 0.0

    for row in rows:
        pnl = float(row.net_pnl_usd)
        equity += pnl
        if pnl < 0.0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
            worst_tail_r = max(
                worst_tail_r,
                (-pnl) / float(row.initial_stop_risk_usd),
            )
        else:
            losing_streak = 0

        if equity >= peak:
            if underwater_start is not None:
                max_recovery_s = max(
                    max_recovery_s,
                    (row.closed_at_utc - underwater_start).total_seconds(),
                )
                underwater_start = None
            peak = equity
        else:
            max_dd = max(max_dd, peak - equity)
            if underwater_start is None:
                underwater_start = row.closed_at_utc

    if underwater_start is not None and rows:
        max_recovery_s = max(
            max_recovery_s,
            (rows[-1].closed_at_utc - underwater_start).total_seconds(),
        )

    return PathDiagnostics(
        n=len(rows),
        max_drawdown_usd=max_dd,
        longest_losing_streak=max_losing_streak,
        max_recovery_duration_s=max_recovery_s,
        sample_ends_underwater=underwater_start is not None,
        worst_tail_loss_r=worst_tail_r,
        resampled_path_stress_status="UNBOUND_POLICY",
        resampled_path_stress_reason=(
            "source requires resampled/bootstrapped path stress where sample "
            "permits but does not bind sample threshold, iterations, or seed policy"
        ),
    )


@dataclass(frozen=True, slots=True)
class ConcentrationTrade:
    trade_id: str
    net_pnl_usd: float
    asset_id: str
    side: str
    regime_label: str
    fold_id: str | None = None

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id is required")
        if not math.isfinite(float(self.net_pnl_usd)):
            raise ValueError("net_pnl_usd must be finite")
        for name in ("asset_id", "side", "regime_label"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")


def concentration_diagnostics(
    trades: Iterable[ConcentrationTrade],
) -> dict[str, object]:
    rows = tuple(trades)
    ids = [row.trade_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate trade_id in concentration sample")

    total_net = sum(float(row.net_pnl_usd) for row in rows)
    positives = sorted(
        (float(row.net_pnl_usd) for row in rows if row.net_pnl_usd > 0.0),
        reverse=True,
    )
    if total_net > 0.0 and positives:
        largest_pct = positives[0] / total_net
        top_n = max(1, math.ceil(len(rows) * 0.10))
        top_decile_pct = sum(positives[:top_n]) / total_net
    else:
        largest_pct = None
        top_decile_pct = None

    fold_totals: dict[str, float] = {}
    for row in rows:
        if row.fold_id is not None:
            fold_totals[row.fold_id] = (
                fold_totals.get(row.fold_id, 0.0) + float(row.net_pnl_usd)
            )
    best_fold_pct = None
    if total_net > 0.0 and fold_totals:
        best_fold_pct = max(fold_totals.values()) / total_net

    def max_count_share(field: str) -> float | None:
        if not rows:
            return None
        counts: dict[str, int] = {}
        for row in rows:
            key = str(getattr(row, field))
            counts[key] = counts.get(key, 0) + 1
        return max(counts.values()) / len(rows)

    return {
        "largest_trade_pct_total_pnl": largest_pct,
        "top_decile_trade_pct_total_pnl": top_decile_pct,
        "best_fold_pct_total_pnl": best_fold_pct,
        "asset_concentration": {
            "measure": "max_trade_count_share",
            "value": max_count_share("asset_id"),
        },
        "side_concentration": {
            "measure": "max_trade_count_share",
            "value": max_count_share("side"),
        },
        "regime_concentration": {
            "measure": "max_trade_count_share",
            "value": max_count_share("regime_label"),
        },
    }


@dataclass(frozen=True, slots=True)
class PortfolioRouteOutcome:
    episode_id: str
    at_utc: datetime
    route_id: str
    net_pnl_usd: float
    initial_stop_risk_usd: float
    expected_return_usd: float
    stop_hit: bool
    broker_local_profitable_rejection: bool = False
    same_bet_group: str | None = None

    def __post_init__(self) -> None:
        if not self.episode_id or not self.route_id:
            raise ValueError("episode_id and route_id are required")
        if self.at_utc.tzinfo is None:
            raise ValueError("at_utc must be timezone-aware")
        for name in ("net_pnl_usd", "initial_stop_risk_usd", "expected_return_usd"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if float(self.initial_stop_risk_usd) < 0.0:
            raise ValueError("initial_stop_risk_usd cannot be negative")


def _series_max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def portfolio_diagnostics(
    outcomes: Iterable[PortfolioRouteOutcome],
    *,
    firm_equity_usd: float,
    portfolio_risk_fraction: float = float(PORTFOLIO_RISK_FRACTION),
) -> dict[str, object]:
    rows = tuple(outcomes)
    if not math.isfinite(float(firm_equity_usd)) or float(firm_equity_usd) <= 0:
        raise ValueError("firm_equity_usd must be positive")
    if (
        not math.isfinite(float(portfolio_risk_fraction))
        or not 0.0 < float(portfolio_risk_fraction) <= 1.0
    ):
        raise ValueError("portfolio_risk_fraction must be in (0,1]")

    keys = [(row.episode_id, row.route_id) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate route outcome in portfolio episode")

    episodes: dict[str, list[PortfolioRouteOutcome]] = {}
    episode_times: dict[str, datetime] = {}
    routes: set[str] = set()
    for row in rows:
        episodes.setdefault(row.episode_id, []).append(row)
        episode_times[row.episode_id] = min(
            episode_times.get(row.episode_id, row.at_utc),
            row.at_utc,
        )
        routes.add(row.route_id)

    co_loss: dict[str, dict[str, float | int]] = {}
    for left, right in combinations(sorted(routes), 2):
        present = 0
        both_loss = 0
        for episode_rows in episodes.values():
            by_route = {row.route_id: row for row in episode_rows}
            if left in by_route and right in by_route:
                present += 1
                if (
                    by_route[left].net_pnl_usd < 0.0
                    and by_route[right].net_pnl_usd < 0.0
                ):
                    both_loss += 1
        if present:
            co_loss[f"{left}|{right}"] = {
                "both_present_count": present,
                "both_loss_count": both_loss,
                "both_loss_rate": both_loss / present,
            }

    limit_usd = float(firm_equity_usd) * float(portfolio_risk_fraction)
    episode_stress: dict[str, float] = {}
    for episode_id, episode_rows in episodes.items():
        episode_stress[episode_id] = sum(
            float(row.initial_stop_risk_usd)
            for row in episode_rows
            if row.stop_hit
        )
    max_stress = max(episode_stress.values(), default=0.0)

    ordered_episode_ids = sorted(
        episodes,
        key=lambda episode_id: (episode_times[episode_id], episode_id),
    )
    portfolio_episode_pnl = [
        sum(float(row.net_pnl_usd) for row in episodes[episode_id])
        for episode_id in ordered_episode_ids
    ]
    full_dd = _series_max_drawdown(portfolio_episode_pnl)

    marginal: dict[str, dict[str, float]] = {}
    for route_id in sorted(routes):
        route_rows = [row for row in rows if row.route_id == route_id]
        without_route = [
            sum(
                float(row.net_pnl_usd)
                for row in episodes[episode_id]
                if row.route_id != route_id
            )
            for episode_id in ordered_episode_ids
        ]
        without_dd = _series_max_drawdown(without_route)
        marginal[route_id] = {
            "mean_expected_return_usd": (
                sum(float(row.expected_return_usd) for row in route_rows)
                / len(route_rows)
            ),
            "mean_stop_risk_usd": (
                sum(float(row.initial_stop_risk_usd) for row in route_rows)
                / len(route_rows)
            ),
            "marginal_drawdown_usd": full_dd - without_dd,
        }

    rejected = [
        row for row in rows
        if row.broker_local_profitable_rejection
        and row.expected_return_usd > 0.0
    ]

    overlap_episode_count = 0
    overlap_groups: dict[str, int] = {}
    for episode_rows in episodes.values():
        groups: dict[str, int] = {}
        for row in episode_rows:
            if row.same_bet_group:
                groups[row.same_bet_group] = groups.get(row.same_bet_group, 0) + 1
        overlapping = {
            group: count for group, count in groups.items() if count >= 2
        }
        if overlapping:
            overlap_episode_count += 1
            for group, count in overlapping.items():
                overlap_groups[group] = overlap_groups.get(group, 0) + count

    episode_count = len(episodes)
    return {
        "co_loss": co_loss,
        "simultaneous_loss_stress": {
            "portfolio_limit_fraction": float(portfolio_risk_fraction),
            "portfolio_limit_usd": limit_usd,
            "max_stop_risk_usd": max_stress,
            "max_utilization": (max_stress / limit_usd if limit_usd else 0.0),
            "breached": max_stress > limit_usd,
            "by_episode": dict(sorted(episode_stress.items())),
        },
        "marginal_contribution": marginal,
        "capital_fragmentation": {
            "profitable_rejection_count": len(rejected),
            "rejected_expected_return_usd": sum(
                float(row.expected_return_usd) for row in rejected
            ),
        },
        "opportunity_overlap": {
            "episode_count": episode_count,
            "overlap_episode_count": overlap_episode_count,
            "overlap_episode_rate": (
                overlap_episode_count / episode_count if episode_count else 0.0
            ),
            "explicit_same_bet_groups": dict(sorted(overlap_groups.items())),
            "inference_policy": "explicit_group_only",
        },
        "portfolio_max_drawdown_usd": full_dd,
    }
