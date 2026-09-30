"""Pure BTC/ETH PAPER-prototype entry planning.

This module converts one completed-bar feature snapshot plus one current executable
market observation into the exact inputs required by Scout/Sniper/Risk/Clerk.

It does not mutate the Firm book and cannot submit or fill an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib

from aether_vnext.costs import CostBreakdown, modeled_round_trip_cost
from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.execution import entry_fill_price
from aether_vnext.exit_plan import ExitPlan, ProfitTakePolicy, TrailingPolicy
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.playbook_engine import ClosedBarRuntimeDecision, resolve_closed_bar_runtime
from aether_vnext.playbook_exits import ExitGeometry, build_exit_geometry
from aether_vnext.playbook_runtime import volatility_band
from aether_vnext.playbooks import playbook
from aether_vnext.prototype_crypto_features import PrototypeCryptoFeatureSnapshot
from aether_vnext.regime import RegimeTags
from aether_vnext.registry import registry_row


PROTOTYPE_CRYPTO_PLAYBOOK_ID = "pb_crypto_swing_v1_2"
PROTOTYPE_COST_EDGE_MULTIPLE = 1.40


@dataclass(frozen=True, slots=True)
class PrototypeEntryIds:
    firm_event_id: str
    setup_id: str
    ticket_id: str
    exit_plan_id: str
    order_intent_id: str
    trade_id: str

    def event_id(self, stage: str) -> str:
        normalized = str(stage).strip().lower().replace("_", "-")
        if not normalized:
            raise ValueError("stage is required")
        digest = hashlib.sha256(
            f"{self.firm_event_id}|{normalized}".encode("utf-8")
        ).hexdigest()[:24]
        return f"evt-prototype-{normalized}-{digest}"


@dataclass(frozen=True, slots=True)
class PrototypeCryptoEntryPlan:
    asset_id: str
    trigger_close_utc: datetime
    eligible: bool
    reason: str
    runtime_decision: ClosedBarRuntimeDecision
    regime_tags: RegimeTags
    ids: PrototypeEntryIds
    entry_reference_price: float | None
    geometry: ExitGeometry | None
    exit_plan: ExitPlan | None
    estimated_cost_per_unit: CostBreakdown | None
    invalidation_hit: bool

    @property
    def hard_stop_price(self) -> float | None:
        return None if self.geometry is None else self.geometry.hard_stop_price

    @property
    def first_target_price(self) -> float | None:
        return None if self.geometry is None else self.geometry.first_target_price


def _stable_id(prefix: str, *, asset_id: str, trigger_close_utc: datetime) -> str:
    raw = "|".join(
        (
            "aether-prototype-entry-v1",
            prefix,
            asset_id,
            trigger_close_utc.isoformat(),
            CONFIGURATION_HASH,
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-prototype-{asset_id}-{digest}"


def prototype_entry_ids(
    *,
    asset_id: str,
    trigger_close_utc: datetime,
) -> PrototypeEntryIds:
    if trigger_close_utc.tzinfo is None:
        raise ValueError("trigger_close_utc must be timezone-aware")
    asset = str(asset_id).strip().lower()
    if asset not in {"btc", "eth"}:
        raise ValueError("prototype entry IDs support btc/eth only")
    return PrototypeEntryIds(
        firm_event_id=_stable_id("firm", asset_id=asset, trigger_close_utc=trigger_close_utc),
        setup_id=_stable_id("setup", asset_id=asset, trigger_close_utc=trigger_close_utc),
        ticket_id=_stable_id("ticket", asset_id=asset, trigger_close_utc=trigger_close_utc),
        exit_plan_id=_stable_id("exit", asset_id=asset, trigger_close_utc=trigger_close_utc),
        order_intent_id=_stable_id("intent", asset_id=asset, trigger_close_utc=trigger_close_utc),
        trade_id=_stable_id("trade", asset_id=asset, trigger_close_utc=trigger_close_utc),
    )


def _regime_tags(feature: PrototypeCryptoFeatureSnapshot) -> RegimeTags:
    return RegimeTags(
        trend_range=(
            "trend_up"
            if feature.daily_ema20 > feature.daily_ema50
            else "not_trend_up"
        ),
        realized_volatility_band=volatility_band(
            feature.volatility.percentile
        ).value,
        session="crypto_24x7",
        spread_cost_band="evaluated_at_clerk",
        event_risk_state="not_bound_for_prototype",
        data_quality_state="completed_kraken_bar",
        as_of_utc=feature.trigger_close_utc,
    )


def _exit_plan(
    *,
    ids: PrototypeEntryIds,
    geometry: ExitGeometry,
) -> ExitPlan:
    if not geometry.source_complete:
        raise ValueError("prototype entry requires a source-complete ExitPlan")
    if geometry.hard_stop_price is None:
        raise ValueError("prototype entry requires a hard stop")
    return ExitPlan(
        exit_plan_id=ids.exit_plan_id,
        version="prototype-crypto-swing-exit-v1",
        hard_stop_price=geometry.hard_stop_price,
        structure_rule_id=(
            "frozen_breakout"
            if geometry.structure_invalidation_level is not None
            else None
        ),
        time_stop_deadline_utc=geometry.time_stop_deadline_utc,
        trailing_policy=TrailingPolicy(
            enabled=False,
            start_condition=None,
            ratchet_rule=None,
            never_loosen=True,
        ),
        profit_take_policy=ProfitTakePolicy(
            enabled=False,
            rule_id=None,
        ),
        # Crypto is 24x7, so there is no session-close flatten rule.
        session_close_policy="hold",
        # Never manufacture an exit from a stale mark; admission/fill remain
        # fail-closed until a fresh executable observation exists.
        stale_mark_policy="hold",
        governor_halt_behavior="flatten",
        created_from_playbook_version=playbook(
            PROTOTYPE_CRYPTO_PLAYBOOK_ID
        ).version,
    )


def build_prototype_crypto_entry_plan(
    *,
    feature: PrototypeCryptoFeatureSnapshot,
    current_observation: MarketObservation,
    as_of_utc: datetime,
) -> PrototypeCryptoEntryPlan:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    asset = feature.asset_id
    if asset not in {"btc", "eth"}:
        raise ValueError("prototype entry supports btc/eth only")
    if current_observation.asset_id != asset:
        raise ValueError("current observation asset mismatch")
    if feature.trigger_close_utc > as_of_utc:
        raise ValueError("feature snapshot cannot be from the future")

    ids = prototype_entry_ids(
        asset_id=asset,
        trigger_close_utc=feature.trigger_close_utc,
    )
    decision = resolve_closed_bar_runtime(
        asset_id=asset,
        horizon="daily_swing",
        family_a=(feature.family_a,),
    )
    tags = _regime_tags(feature)

    if not decision.watch_candidates:
        return PrototypeCryptoEntryPlan(
            asset_id=asset,
            trigger_close_utc=feature.trigger_close_utc,
            eligible=False,
            reason=decision.reason,
            runtime_decision=decision,
            regime_tags=tags,
            ids=ids,
            entry_reference_price=None,
            geometry=None,
            exit_plan=None,
            estimated_cost_per_unit=None,
            invalidation_hit=False,
        )

    candidate = decision.watch_candidates[0]
    if candidate.playbook_id != PROTOTYPE_CRYPTO_PLAYBOOK_ID:
        raise RuntimeError("unexpected prototype crypto playbook")
    if not candidate.exit_contract_complete:
        raise RuntimeError("prototype crypto playbook ExitPlan is incomplete")
    if current_observation.quality_state is not QualityState.HEALTHY:
        return PrototypeCryptoEntryPlan(
            asset_id=asset,
            trigger_close_utc=feature.trigger_close_utc,
            eligible=False,
            reason="market_not_healthy",
            runtime_decision=decision,
            regime_tags=tags,
            ids=ids,
            entry_reference_price=None,
            geometry=None,
            exit_plan=None,
            estimated_cost_per_unit=None,
            invalidation_hit=False,
        )
    if (
        current_observation.bid is None
        or current_observation.ask is None
        or current_observation.spread_abs is None
    ):
        return PrototypeCryptoEntryPlan(
            asset_id=asset,
            trigger_close_utc=feature.trigger_close_utc,
            eligible=False,
            reason="two_sided_quote_required",
            runtime_decision=decision,
            regime_tags=tags,
            ids=ids,
            entry_reference_price=None,
            geometry=None,
            exit_plan=None,
            estimated_cost_per_unit=None,
            invalidation_hit=False,
        )

    entry = entry_fill_price(
        current_observation,
        position_side="long",
    )
    geometry = build_exit_geometry(
        playbook(PROTOTYPE_CRYPTO_PLAYBOOK_ID),
        side="long",
        entry_price=entry,
        atr=feature.atr14,
        filled_at_utc=as_of_utc,
        frozen_breakout_level=feature.prior_20h_high,
        prior_range_low=feature.prior_20h_low,
    )
    if geometry.first_target_price is None:
        raise RuntimeError("crypto swing first target is required")

    costs = modeled_round_trip_cost(
        registry_row(asset),
        qty=1.0,
        entry_price=entry,
        exit_reference_price=geometry.first_target_price,
        spread_abs=float(current_observation.spread_abs),
        entry_side="buy",
        exit_side="sell",
        cost_edge_multiple=PROTOTYPE_COST_EDGE_MULTIPLE,
    )

    invalidation_hit = (
        float(current_observation.bid) <= float(feature.prior_20h_high)
    )
    return PrototypeCryptoEntryPlan(
        asset_id=asset,
        trigger_close_utc=feature.trigger_close_utc,
        eligible=True,
        reason="family_a_watch",
        runtime_decision=decision,
        regime_tags=tags,
        ids=ids,
        entry_reference_price=entry,
        geometry=geometry,
        exit_plan=_exit_plan(ids=ids, geometry=geometry),
        estimated_cost_per_unit=costs,
        invalidation_hit=invalidation_hit,
    )
