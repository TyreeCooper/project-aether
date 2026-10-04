"""Source-bound exit evaluation for Kraken crypto PAPER trades.

The frozen crypto-swing exit precedence is:
1. authenticated Governor HALT -> flatten;
2. hard stop triggered on current executable bid;
3. structure invalidation only on a FUTURE COMPLETED 1h close below the frozen
   breakout level;
4. five-calendar-day time stop.

Trailing and profit-taking remain disabled. Crypto is 24x7, so no session-close
flatten is invented. Stale market data does not manufacture a hard-stop or
structure exit; a due Governor/time exit may be requested and will wait for a
fresh executable quote at the existing paper close-fill boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.execution import stop_triggered
from aether_vnext.exit_plan import ExitReason
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar


@dataclass(frozen=True, slots=True)
class PrototypeCryptoExitDecision:
    should_flatten: bool
    exit_reason: ExitReason | None
    reason: str


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be positive")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _deadline(payload: Mapping[str, Any]) -> datetime | None:
    raw = payload.get("time_stop_deadline_utc")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _aware(raw, "time_stop_deadline_utc")
    text = str(raw).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    return _aware(parsed, "time_stop_deadline_utc")


def _validate_frozen_crypto_plan(payload: Mapping[str, Any]) -> None:
    if str(payload.get("structure_rule_id") or "") != "frozen_breakout":
        raise RuntimeError(
            "prototype crypto OPEN trade missing frozen-breakout structure rule"
        )
    trailing = dict(payload.get("trailing_policy") or {})
    if bool(trailing.get("enabled")):
        raise RuntimeError("prototype crypto trailing exit is not source-bound")
    profit = dict(payload.get("profit_take_policy") or {})
    if bool(profit.get("enabled")):
        raise RuntimeError("prototype crypto profit-taking is not source-bound")
    if str(payload.get("session_close_policy") or "") != "hold":
        raise RuntimeError("prototype crypto must remain 24x7 across session boundaries")
    if str(payload.get("stale_mark_policy") or "") != "hold":
        raise RuntimeError("prototype crypto stale-mark action is not source-bound")
    if str(payload.get("governor_halt_behavior") or "") != "flatten":
        raise RuntimeError("prototype crypto Governor HALT must flatten")


def _completed_structure_close(
    bar: PrototypeMarketBar | None,
    *,
    asset_id: str,
    opened_at_utc: datetime,
    as_of_utc: datetime,
) -> float | None:
    if bar is None:
        return None
    if bar.asset_id != asset_id:
        raise ValueError("completed exit bar asset mismatch")
    if bar.interval_seconds != 3600:
        raise ValueError("crypto structure invalidation requires completed 1h bar")
    if bar.source_id != KRAKEN_DAILY_SOURCE_ID:
        raise ValueError(
            "crypto structure invalidation requires direct Kraken REST bar"
        )
    if bar.bucket_close_utc > as_of_utc or bar.available_at_utc > as_of_utc:
        raise ValueError("future/unavailable bar cannot trigger exit")
    # The setup/signal bar itself cannot invalidate a trade opened after it.
    if bar.bucket_close_utc <= opened_at_utc:
        return None
    return float(bar.close)


def evaluate_prototype_crypto_exit(
    *,
    asset_id: str,
    side: str,
    opened_at_utc: datetime,
    exit_plan_payload: Mapping[str, Any],
    frozen_breakout_level: float,
    current_observation: MarketObservation,
    latest_completed_hourly_bar: PrototypeMarketBar | None,
    governor_halted: bool,
    as_of_utc: datetime,
) -> PrototypeCryptoExitDecision:
    """Evaluate one OPEN crypto trade without mutating durable state."""
    asset = str(asset_id).strip().lower()
    if not asset:
        raise ValueError("asset_id is required")
    if str(side).strip().lower() != "long":
        raise ValueError("prototype crypto exit is long-only")
    _aware(opened_at_utc, "opened_at_utc")
    _aware(as_of_utc, "as_of_utc")
    if as_of_utc < opened_at_utc:
        raise ValueError("exit evaluation cannot predate OPEN")
    if current_observation.asset_id != asset:
        raise ValueError("exit market observation asset mismatch")

    payload = dict(exit_plan_payload)
    _validate_frozen_crypto_plan(payload)
    hard_stop = _positive(payload.get("hard_stop_price"), "hard_stop_price")
    breakout = _positive(frozen_breakout_level, "frozen_breakout_level")
    deadline = _deadline(payload)

    # Exact source precedence: HALT outranks every market/structure trigger.
    if governor_halted:
        return PrototypeCryptoExitDecision(
            True,
            ExitReason.GOVERNOR_HALT,
            "governor_halt",
        )

    # Stale/unhealthy market data cannot manufacture hard-stop execution.
    if current_observation.quality_state is QualityState.HEALTHY:
        if stop_triggered(
            current_observation,
            position_side="long",
            hard_stop_price=hard_stop,
        ):
            return PrototypeCryptoExitDecision(
                True,
                ExitReason.HARD_STOP,
                "hard_stop_on_bid",
            )

    completed_close = _completed_structure_close(
        latest_completed_hourly_bar,
        asset_id=asset,
        opened_at_utc=opened_at_utc,
        as_of_utc=as_of_utc,
    )
    if completed_close is not None and completed_close < breakout:
        return PrototypeCryptoExitDecision(
            True,
            ExitReason.STRUCTURE,
            "completed_1h_close_below_frozen_breakout",
        )

    if deadline is not None and as_of_utc >= deadline:
        return PrototypeCryptoExitDecision(
            True,
            ExitReason.TIME_STOP,
            "five_calendar_day_time_stop",
        )

    return PrototypeCryptoExitDecision(
        False,
        None,
        "hold",
    )
