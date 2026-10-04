"""Read-only profitability projection for the future AETHER operator surface.

Part IV P10 requires one operator view of profitability evidence while preserving seat
authority. This module is deliberately a pure projection: it accepts immutable evidence
and telemetry and returns display data. It has no Store, Risk, Governor, Clerk, Portfolio,
or Execution mutation API.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from aether_vnext.evidence import ProfitabilityEvidence


@dataclass(frozen=True, slots=True)
class FirmStripInput:
    net_paper_pnl_usd: float
    rolling_expectancy_usd: float | None
    max_drawdown_usd: float
    portfolio_stop_risk_usd: float
    broker_sleeve_health: Mapping[str, str]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "net_paper_pnl_usd",
            "max_drawdown_usd",
            "portfolio_stop_risk_usd",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.rolling_expectancy_usd is not None and not math.isfinite(
            float(self.rolling_expectancy_usd)
        ):
            raise ValueError("rolling_expectancy_usd must be finite")


@dataclass(frozen=True, slots=True)
class ExecutionPanelInput:
    expected_fill_cost_usd: float | None
    realized_fill_cost_usd: float | None
    average_spread_bps: float | None
    average_slippage_bps: float | None
    reject_rate: float | None
    stale_observation_count: int
    invalid_observation_count: int

    def __post_init__(self) -> None:
        for name in (
            "expected_fill_cost_usd",
            "realized_fill_cost_usd",
            "average_spread_bps",
            "average_slippage_bps",
            "reject_rate",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.reject_rate is not None and not 0.0 <= float(self.reject_rate) <= 1.0:
            raise ValueError("reject_rate must be in [0,1]")
        if int(self.stale_observation_count) < 0:
            raise ValueError("stale_observation_count cannot be negative")
        if int(self.invalid_observation_count) < 0:
            raise ValueError("invalid_observation_count cannot be negative")


def _cost_shock_status(evidence: ProfitabilityEvidence) -> dict[str, object]:
    sensitivity = {
        "base": dict(evidence.cost_sensitivity.base),
        "plus25": dict(evidence.cost_sensitivity.plus25),
        "plus50": dict(evidence.cost_sensitivity.plus50),
    }
    out: dict[str, object] = {}
    for label in ("base", "plus25", "plus50"):
        bucket = dict(sensitivity.get(label) or {})
        expectancy = bucket.get("net_expectancy_usd")
        out[label] = {
            "net_expectancy_usd": expectancy,
            "positive": (
                None
                if expectancy is None
                else float(expectancy) > 0.0
            ),
        }
    return out


def _route_row(
    evidence: ProfitabilityEvidence,
    *,
    decay_state: str | None,
    review_state: str | None,
) -> dict[str, object]:
    return {
        "route_id": evidence.route_id,
        "playbook_id": evidence.playbook_id,
        "playbook_version": evidence.playbook_version,
        "configuration_hash": evidence.configuration_hash,
        "n": evidence.n_trades,
        "verdict": evidence.verdict,
        "review_state": review_state,
        "net_expectancy_usd": evidence.net_expectancy_usd,
        "profit_factor": evidence.profit_factor,
        "max_drawdown_usd": evidence.max_drawdown_usd,
        "max_drawdown_pct": evidence.max_drawdown_pct,
        "capture_efficiency": evidence.capture_efficiency,
        "cost_shock_status": _cost_shock_status(evidence),
        "recent_decay_state": decay_state,
        "model_risks": list(evidence.model_risks),
    }


def _review_row(
    evidence: ProfitabilityEvidence,
    *,
    review_state: str | None,
) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "route_id": evidence.route_id,
        "configuration_hash": evidence.configuration_hash,
        "current_review_state": review_state,
        "verdict": evidence.verdict,
        "oos_windows": list(evidence.oos_windows),
        "regime_matrix": dict(evidence.regime_matrix),
        "benchmark_result": dict(evidence.benchmark_result),
        "cost_sensitivity": {
            "base": dict(evidence.cost_sensitivity.base),
            "plus25": dict(evidence.cost_sensitivity.plus25),
            "plus50": dict(evidence.cost_sensitivity.plus50),
        },
        "drawdown": {
            "usd": evidence.max_drawdown_usd,
            "pct": evidence.max_drawdown_pct,
        },
        "capacity_result": dict(evidence.capacity_result),
        "portfolio_contribution": dict(evidence.portfolio_contribution),
    }


def build_profitability_dashboard(
    *,
    firm_strip: FirmStripInput,
    evidence_records: Iterable[ProfitabilityEvidence],
    decay_state_by_route: Mapping[str, str],
    review_state_by_route: Mapping[str, str],
    traffic_funnel: Mapping[str, Any],
    execution_panel: ExecutionPanelInput,
    additional_model_risks: Iterable[str] = (),
) -> dict[str, object]:
    """Return the complete P10 display projection with no mutation authority."""
    evidence = tuple(evidence_records)
    route_ids = [row.route_id for row in evidence]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError(
            "dashboard accepts one current ProfitabilityEvidence record per route"
        )

    route_board = [
        _route_row(
            row,
            decay_state=decay_state_by_route.get(row.route_id),
            review_state=review_state_by_route.get(row.route_id),
        )
        for row in sorted(evidence, key=lambda item: item.route_id)
    ]
    review_panel = [
        _review_row(
            row,
            review_state=review_state_by_route.get(row.route_id),
        )
        for row in sorted(evidence, key=lambda item: item.route_id)
    ]

    model_risks = sorted(
        {
            str(risk)
            for row in evidence
            for risk in row.model_risks
        }
        | {str(risk) for risk in additional_model_risks}
    )

    return {
        "authority": {
            "read_only": True,
            "execution_permission": False,
            "may_mutate_route_state": False,
            "may_mutate_risk": False,
            "may_reset_governor": False,
            "display_law": (
                "profitability evidence is observational; seats and typed "
                "state remain authoritative"
            ),
        },
        "firm_strip": {
            "net_paper_pnl_usd": firm_strip.net_paper_pnl_usd,
            "rolling_expectancy_usd": firm_strip.rolling_expectancy_usd,
            "max_drawdown_usd": firm_strip.max_drawdown_usd,
            "portfolio_stop_risk_usd": firm_strip.portfolio_stop_risk_usd,
            "broker_sleeve_health": dict(firm_strip.broker_sleeve_health),
            "warnings": list(firm_strip.warnings),
        },
        "route_board": route_board,
        "traffic_funnel": dict(traffic_funnel),
        "execution_panel": {
            "expected_fill_cost_usd": execution_panel.expected_fill_cost_usd,
            "realized_fill_cost_usd": execution_panel.realized_fill_cost_usd,
            "average_spread_bps": execution_panel.average_spread_bps,
            "average_slippage_bps": execution_panel.average_slippage_bps,
            "reject_rate": execution_panel.reject_rate,
            "stale_observation_count": execution_panel.stale_observation_count,
            "invalid_observation_count": execution_panel.invalid_observation_count,
        },
        "review_panel": review_panel,
        "model_risk_panel": {
            "known_omissions": model_risks,
        },
    }
