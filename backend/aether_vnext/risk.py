"""AETHER vNext Phase-6 constitutional stop-risk sizing primitives.

This module implements only source-frozen risk math. It deliberately does not
assign assets to clusters, define daily-loss thresholds, or decide how concurrent
pending admissions consume capacity. Those remain separate policy/integration
questions and must not be invented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from aether_vnext.execution import gross_pnl_usd
from aether_vnext.freeze import (
    ASSET_RISK_FRACTION,
    CLUSTER_RISK_FRACTION,
    PORTFOLIO_RISK_FRACTION,
    TRADE_RISK_FRACTION,
)
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.registry import ProductRegistryRow


RISK_EPSILON_USD = 1e-9


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    trade_fraction: float = TRADE_RISK_FRACTION
    asset_fraction: float = ASSET_RISK_FRACTION
    cluster_fraction: float = CLUSTER_RISK_FRACTION
    portfolio_fraction: float = PORTFOLIO_RISK_FRACTION

    def __post_init__(self) -> None:
        limits = (
            ("trade_fraction", self.trade_fraction, TRADE_RISK_FRACTION),
            ("asset_fraction", self.asset_fraction, ASSET_RISK_FRACTION),
            ("cluster_fraction", self.cluster_fraction, CLUSTER_RISK_FRACTION),
            ("portfolio_fraction", self.portfolio_fraction, PORTFOLIO_RISK_FRACTION),
        )
        for name, value, ceiling in limits:
            numeric = float(value)
            if numeric < 0:
                raise ValueError(f"{name} cannot be negative")
            if numeric > ceiling + 1e-15:
                raise ValueError(f"{name} cannot exceed constitutional ceiling")


@dataclass(frozen=True, slots=True)
class RiskLimitsUsd:
    equity_usd: float
    trade_usd: float
    asset_usd: float
    cluster_usd: float
    portfolio_usd: float


@dataclass(frozen=True, slots=True)
class RiskExposure:
    asset_open_risk_usd: float = 0.0
    cluster_open_risk_usd: float = 0.0
    portfolio_open_risk_usd: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("asset_open_risk_usd", self.asset_open_risk_usd),
            ("cluster_open_risk_usd", self.cluster_open_risk_usd),
            ("portfolio_open_risk_usd", self.portfolio_open_risk_usd),
        ):
            if float(value) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskSizeResult:
    ok: bool
    quantity: float
    stop_risk_usd: float
    allowed_risk_usd: float
    reject_code: str | None
    limits: RiskLimitsUsd


def risk_limits_usd(
    equity_usd: float,
    *,
    policy: RiskPolicy = RiskPolicy(),
) -> RiskLimitsUsd:
    equity = float(equity_usd)
    if equity <= 0:
        raise ValueError("equity_usd must be positive")
    return RiskLimitsUsd(
        equity_usd=equity,
        trade_usd=equity * float(policy.trade_fraction),
        asset_usd=equity * float(policy.asset_fraction),
        cluster_usd=equity * float(policy.cluster_fraction),
        portfolio_usd=equity * float(policy.portfolio_fraction),
    )


def stop_risk_usd(
    row: ProductRegistryRow,
    *,
    side: str,
    quantity: float,
    entry_price: float,
    stop_price: float,
) -> float:
    normalized = str(side).strip().lower()
    qty = abs(float(quantity))
    entry = float(entry_price)
    stop = float(stop_price)
    if normalized not in {"long", "short"}:
        raise ValueError("side must be long or short")
    if qty <= 0 or entry <= 0 or stop <= 0:
        raise ValueError("quantity and prices must be positive")
    if normalized == "long" and stop >= entry:
        raise ValueError("bad_stop")
    if normalized == "short" and stop <= entry:
        raise ValueError("bad_stop")

    pnl_at_stop = gross_pnl_usd(
        row,
        position_side=normalized,
        qty=qty,
        entry_price=entry,
        exit_price=stop,
    )
    loss = -float(pnl_at_stop)
    if loss <= 0:
        raise ValueError("bad_stop")
    return loss


def floor_quantity_to_step(quantity: float, step: float) -> float:
    raw = Decimal(str(float(quantity)))
    increment = Decimal(str(float(step)))
    if raw < 0:
        raise ValueError("quantity cannot be negative")
    if increment <= 0:
        raise ValueError("quantity step must be positive")
    # Neutralize sub-ULP float noise before flooring without changing a
    # materially sub-step quantity. The final stop-risk assertion remains the
    # authoritative guard against any quantity exceeding its dollar budget.
    units = (
        (raw / increment) + Decimal("1e-12")
    ).to_integral_value(rounding=ROUND_FLOOR)
    return float(units * increment)


def _capacity_reason(
    *,
    asset_remaining: float,
    cluster_remaining: float,
    portfolio_remaining: float,
) -> ReasonCode | None:
    if asset_remaining <= RISK_EPSILON_USD:
        return ReasonCode.ASSET_RISK_FULL
    if cluster_remaining <= RISK_EPSILON_USD:
        return ReasonCode.CLUSTER_RISK_FULL
    if portfolio_remaining <= RISK_EPSILON_USD:
        return ReasonCode.PORTFOLIO_RISK_FULL
    return None


def size_candidate_to_risk(
    row: ProductRegistryRow,
    *,
    side: str,
    entry_price: float,
    stop_price: float,
    equity_usd: float,
    exposure: RiskExposure = RiskExposure(),
    policy: RiskPolicy = RiskPolicy(),
    broker_margin_cap_qty: float | None = None,
    firm_capital_cap_qty: float | None = None,
) -> RiskSizeResult:
    """Return a rounded executable quantity constrained by the four-layer envelope.

    The caller supplies already-accounted asset/cluster/portfolio open stop-risk.
    This function does not decide cluster membership or pending-admission semantics.
    """
    limits = risk_limits_usd(equity_usd, policy=policy)

    asset_remaining = max(
        limits.asset_usd - float(exposure.asset_open_risk_usd),
        0.0,
    )
    cluster_remaining = max(
        limits.cluster_usd - float(exposure.cluster_open_risk_usd),
        0.0,
    )
    portfolio_remaining = max(
        limits.portfolio_usd - float(exposure.portfolio_open_risk_usd),
        0.0,
    )
    blocked = _capacity_reason(
        asset_remaining=asset_remaining,
        cluster_remaining=cluster_remaining,
        portfolio_remaining=portfolio_remaining,
    )
    if blocked is not None:
        return RiskSizeResult(
            ok=False,
            quantity=0.0,
            stop_risk_usd=0.0,
            allowed_risk_usd=0.0,
            reject_code=blocked.value,
            limits=limits,
        )

    allowed = max(
        min(
            limits.trade_usd,
            asset_remaining,
            cluster_remaining,
            portfolio_remaining,
        ),
        0.0,
    )
    if allowed <= RISK_EPSILON_USD:
        return RiskSizeResult(
            ok=False,
            quantity=0.0,
            stop_risk_usd=0.0,
            allowed_risk_usd=allowed,
            reject_code=ReasonCode.TOO_SMALL.value,
            limits=limits,
        )

    try:
        per_unit_risk = stop_risk_usd(
            row,
            side=side,
            quantity=1.0,
            entry_price=entry_price,
            stop_price=stop_price,
        )
    except ValueError as exc:
        if str(exc) == "bad_stop":
            return RiskSizeResult(
                ok=False,
                quantity=0.0,
                stop_risk_usd=0.0,
                allowed_risk_usd=allowed,
                reject_code=ReasonCode.BAD_STOP.value,
                limits=limits,
            )
        raise

    raw_qty = allowed / per_unit_risk
    quantity_caps = [raw_qty]
    if row.maximum_quantity is not None:
        quantity_caps.append(float(row.maximum_quantity))
    for cap_name, cap in (
        ("broker_margin_cap_qty", broker_margin_cap_qty),
        ("firm_capital_cap_qty", firm_capital_cap_qty),
    ):
        if cap is None:
            continue
        numeric = float(cap)
        if numeric < 0:
            raise ValueError(f"{cap_name} cannot be negative")
        quantity_caps.append(numeric)

    quantity = floor_quantity_to_step(
        min(quantity_caps),
        float(row.quantity_step),
    )
    if quantity <= 0 or quantity + 1e-15 < float(row.minimum_quantity):
        return RiskSizeResult(
            ok=False,
            quantity=0.0,
            stop_risk_usd=0.0,
            allowed_risk_usd=allowed,
            reject_code=ReasonCode.TOO_SMALL.value,
            limits=limits,
        )

    actual_risk = stop_risk_usd(
        row,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
    )
    if actual_risk > allowed + 1e-6:
        raise AssertionError("rounded executable quantity exceeds allowed risk")

    return RiskSizeResult(
        ok=True,
        quantity=quantity,
        stop_risk_usd=actual_risk,
        allowed_risk_usd=allowed,
        reject_code=None,
        limits=limits,
    )
