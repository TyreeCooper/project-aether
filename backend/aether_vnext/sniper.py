"""Deterministic Sniper WATCH -> FIRE contract for AETHER vNext Phase 8.

Sniper consumes a durable Scout WATCH and one completed trigger bar. It validates
the frozen trigger/stop contract and emits a deterministic FIRE decision or one
canonical reject code. It does not size Risk, calculate Clerk economics, or move
the Firm book.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib

from aether_vnext.bars import Bar
from aether_vnext.domain import MarketObservation, QualityState, Setup, SetupState
from aether_vnext.playbooks import playbook
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.registry import registry_row


@dataclass(frozen=True, slots=True)
class SniperDecision:
    fire: bool
    signal_key: str
    stop_price: float | None
    reject_code: str | None


def signal_key_for_setup(setup: Setup) -> str:
    close_ts = setup.trigger_bar_close_exchange_ts
    if close_ts is None or close_ts.tzinfo is None:
        raise ValueError("Setup trigger-bar close timestamp is required")
    raw = "|".join(
        (
            setup.setup_id,
            setup.lineage.asset_id,
            setup.horizon,
            setup.side,
            close_ts.isoformat(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluate_sniper_fire(
    setup: Setup,
    *,
    completed_bar: Bar | None,
    current_observation: MarketObservation,
    hard_stop_price: float | None,
    as_of_utc: datetime,
    grain_valid: bool,
    invalidation_hit: bool,
) -> SniperDecision:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if setup.exit_contract_complete is not True:
        raise ValueError(
            "incomplete playbook ExitPlan contract cannot materialize FIRE"
        )
    if setup.exit_contract_gap is not None:
        raise ValueError("complete exit contract cannot carry a gap")

    signal_key = signal_key_for_setup(setup)
    if setup.state is not SetupState.WATCH:
        return SniperDecision(
            False, signal_key, hard_stop_price, ReasonCode.STALE_SETUP.value
        )

    spec = playbook(str(setup.lineage.playbook_id))
    if spec.version != setup.lineage.playbook_version:
        raise ValueError("Setup playbook version drift")
    if spec.horizon != setup.horizon:
        raise ValueError("Setup horizon drift")

    if completed_bar is None:
        return SniperDecision(
            False, signal_key, hard_stop_price, ReasonCode.FORMING_BAR.value
        )
    close_ts = setup.trigger_bar_close_exchange_ts
    if (
        completed_bar.bucket_close_utc > as_of_utc
        or close_ts is None
        or completed_bar.bucket_close_utc != close_ts
    ):
        code = (
            ReasonCode.FORMING_BAR.value
            if completed_bar.bucket_close_utc > as_of_utc
            else ReasonCode.NO_COMPLETED_BREAKOUT.value
        )
        return SniperDecision(False, signal_key, hard_stop_price, code)
    if (
        completed_bar.asset_id != setup.lineage.asset_id
        or completed_bar.interval != spec.trigger_interval
    ):
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.NO_COMPLETED_BREAKOUT.value,
        )
    if not grain_valid:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.NO_COMPLETED_BREAKOUT.value,
        )
    if invalidation_hit:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.INVALIDATION_HIT.value,
        )

    if current_observation.asset_id != setup.lineage.asset_id:
        raise ValueError("current observation asset mismatch")
    if current_observation.quality_state in {
        QualityState.STALE,
        QualityState.INVALID,
    }:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.MARKET_STALE.value,
        )

    product = registry_row(setup.lineage.asset_id)
    side = setup.side.lower()
    if (
        (side == "long" and not product.long_supported)
        or (side == "short" and not product.short_supported)
    ):
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.PRODUCT_SIDE_UNSUPPORTED.value,
        )

    if hard_stop_price is None or float(hard_stop_price) <= 0:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.ILLEGAL_STOP_SIDE.value,
        )

    if side == "long":
        mark_side = current_observation.bid
        legal = mark_side is not None and float(hard_stop_price) < float(mark_side)
    elif side == "short":
        mark_side = current_observation.ask
        legal = mark_side is not None and float(hard_stop_price) > float(mark_side)
    else:
        raise ValueError("Setup side must be long or short")

    if mark_side is None:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.MARKET_STALE.value,
        )
    if not legal:
        return SniperDecision(
            False,
            signal_key,
            hard_stop_price,
            ReasonCode.ILLEGAL_STOP_SIDE.value,
        )

    return SniperDecision(True, signal_key, float(hard_stop_price), None)
