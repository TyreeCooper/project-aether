"""Source-bound trend requirements for executable Family-A playbooks.

Playbook Pack v1.4 binds the trend indicator rule and timeframe separately from the
trigger interval for several routes. Replay must not substitute trigger-interval EMA
values when the source requires a higher timeframe.

This module contains source-authority metadata only. It does not calculate indicators,
select bars, infer BTC dependency state, or evaluate setups.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class TrendRuleKind(StrEnum):
    EMA20_SLOPE = "ema20_slope"
    EMA20_EMA50_LEVEL = "ema20_ema50_level"


@dataclass(frozen=True, slots=True)
class PlaybookTrendRequirement:
    playbook_id: str
    interval: timedelta
    interval_label: str
    rule_kind: TrendRuleKind

    def __post_init__(self) -> None:
        if (
            not isinstance(self.playbook_id, str)
            or not self.playbook_id
            or self.playbook_id != self.playbook_id.strip()
        ):
            raise ValueError("playbook_id must be canonical text")
        if self.interval <= timedelta(0):
            raise ValueError("trend interval must be positive")
        if (
            not isinstance(self.interval_label, str)
            or not self.interval_label
            or self.interval_label != self.interval_label.strip()
        ):
            raise ValueError("interval_label must be canonical text")
        if not isinstance(self.rule_kind, TrendRuleKind):
            raise ValueError("rule_kind must be a TrendRuleKind")


_MIN15 = timedelta(minutes=15)
_HOUR1 = timedelta(hours=1)
_DAY1 = timedelta(days=1)


def _level(playbook_id: str, interval: timedelta, label: str) -> PlaybookTrendRequirement:
    return PlaybookTrendRequirement(
        playbook_id=playbook_id,
        interval=interval,
        interval_label=label,
        rule_kind=TrendRuleKind.EMA20_EMA50_LEVEL,
    )


def _slope(playbook_id: str, interval: timedelta, label: str) -> PlaybookTrendRequirement:
    return PlaybookTrendRequirement(
        playbook_id=playbook_id,
        interval=interval,
        interval_label=label,
        rule_kind=TrendRuleKind.EMA20_SLOPE,
    )


_TREND_REQUIREMENTS = {
    # Crypto: 1h trigger, daily trend.
    "pb_crypto_swing_v1_2": _level(
        "pb_crypto_swing_v1_2", _DAY1, "1d"
    ),
    "pb_eth_rider_v1_2": _level(
        "pb_eth_rider_v1_2", _DAY1, "1d"
    ),
    # FX: intraday uses 1h EMA20 slope; swing uses daily EMA20/EMA50.
    "pb_fx_intraday_v1_2": _slope(
        "pb_fx_intraday_v1_2", _HOUR1, "1h"
    ),
    "pb_fx_swing_v1_2": _level(
        "pb_fx_swing_v1_2", _DAY1, "1d"
    ),
    # Index futures: source binds 15m trend for all three horizons.
    "pb_idx_scalp_v1_2": _level(
        "pb_idx_scalp_v1_2", _MIN15, "15m"
    ),
    "pb_idx_intraday_v1_2": _level(
        "pb_idx_intraday_v1_2", _MIN15, "15m"
    ),
    "pb_idx_swing_v1_2": _level(
        "pb_idx_swing_v1_2", _MIN15, "15m"
    ),
    # Metal and energy: 15m trigger, 1h higher-timeframe bias.
    "pb_metal_intraday_v1_2": _level(
        "pb_metal_intraday_v1_2", _HOUR1, "1h"
    ),
    "pb_metal_swing_v1_2": _level(
        "pb_metal_swing_v1_2", _HOUR1, "1h"
    ),
    "pb_energy_intraday_v1_2": _level(
        "pb_energy_intraday_v1_2", _HOUR1, "1h"
    ),
    "pb_energy_swing_v1_2": _level(
        "pb_energy_swing_v1_2", _HOUR1, "1h"
    ),
    # Rates: 1h trigger, daily bias.
    "pb_rates_swing_v1_2": _level(
        "pb_rates_swing_v1_2", _DAY1, "1d"
    ),
    # Equities: source binds 15m trend for scalp/intraday/swing.
    "pb_eq_scalp_v1_2": _level(
        "pb_eq_scalp_v1_2", _MIN15, "15m"
    ),
    "pb_eq_intraday_v1_2": _level(
        "pb_eq_intraday_v1_2", _MIN15, "15m"
    ),
    "pb_eq_swing_v1_2": _level(
        "pb_eq_swing_v1_2", _MIN15, "15m"
    ),
}


PLAYBOOK_TREND_REQUIREMENTS: Final = MappingProxyType(_TREND_REQUIREMENTS)


def trend_requirement(playbook_id: str) -> PlaybookTrendRequirement:
    """Return the source-bound trend rule for one executable Family-A playbook."""
    value = str(playbook_id).strip()
    if not value:
        raise ValueError("playbook_id is required")
    try:
        return PLAYBOOK_TREND_REQUIREMENTS[value]
    except KeyError as exc:
        raise ValueError(
            f"no source-bound executable trend requirement: {value}"
        ) from exc
