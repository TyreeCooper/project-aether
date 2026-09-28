"""Source-bound Family-B failed-break reconstruction for HELD_OUT replay."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Sequence

from aether_vnext.bars import Bar
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec
from aether_vnext.replay_family_adapter import FamilyBReplayState


class ReplayReferenceKind(StrEnum):
    PRIOR_20_CLOSED_BARS = "prior_20_closed_bars"
    PRIOR_COMPLETED_SESSION = "prior_completed_session"
    PRIOR_OFFICIAL_RTH_DAY = "prior_official_rth_day"


_FAMILY_B_REFERENCE_KIND: Final = MappingProxyType({
    "pb_crypto_failed_break_v1_3": ReplayReferenceKind.PRIOR_20_CLOSED_BARS,
    "pb_eth_failed_break_v1_3": ReplayReferenceKind.PRIOR_20_CLOSED_BARS,
    "pb_fx_failed_session_v1_3": ReplayReferenceKind.PRIOR_COMPLETED_SESSION,
    "pb_fx_failed_swing_v1_3": ReplayReferenceKind.PRIOR_20_CLOSED_BARS,
    "pb_idx_failed_v1_3": ReplayReferenceKind.PRIOR_OFFICIAL_RTH_DAY,
    "pb_metal_failed_v1_3": ReplayReferenceKind.PRIOR_COMPLETED_SESSION,
    "pb_energy_failed_v1_3": ReplayReferenceKind.PRIOR_COMPLETED_SESSION,
    "pb_rates_failed_v1_3": ReplayReferenceKind.PRIOR_20_CLOSED_BARS,
    "pb_eq_failed_v1_3": ReplayReferenceKind.PRIOR_OFFICIAL_RTH_DAY,
})


@dataclass(frozen=True, slots=True)
class FrozenBreakReference:
    asset_id: str
    kind: ReplayReferenceKind
    high: float
    low: float
    mid: float
    frozen_at_utc: datetime
    source_ref: str

    def __post_init__(self) -> None:
        if not self.asset_id or self.asset_id != self.asset_id.strip().lower():
            raise ValueError("asset_id must be canonical lowercase")
        high, low, mid = float(self.high), float(self.low), float(self.mid)
        if low <= 0 or high <= low:
            raise ValueError("frozen reference high/low are invalid")
        expected = (high + low) / 2.0
        if abs(mid - expected) > max(1e-12, abs(expected) * 1e-12):
            raise ValueError("frozen reference mid must equal range midpoint")
        if self.frozen_at_utc.tzinfo is None:
            raise ValueError("frozen_at_utc must be timezone-aware")
        if not self.source_ref or self.source_ref != self.source_ref.strip():
            raise ValueError("source_ref must be canonical text")


def expected_family_b_reference_kind(spec: PlaybookSpec) -> ReplayReferenceKind:
    if spec.family is not PlaybookFamily.B:
        raise ValueError("reference-kind lookup requires a Family-B playbook")
    try:
        return _FAMILY_B_REFERENCE_KIND[spec.playbook_id]
    except KeyError as exc:
        raise ValueError(
            f"Family-B playbook has no frozen reference kind: {spec.playbook_id}"
        ) from exc


def reconstruct_family_b_state(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    bars: Sequence[Bar],
    reference: FrozenBreakReference,
    break_bar_close_utc: datetime,
    counter_trend_condition: bool,
    position_key_open: bool = False,
    locate_ok: bool | None = None,
) -> FamilyBReplayState:
    if spec.family is not PlaybookFamily.B:
        raise ValueError("failed-break reconstruction requires a Family-B playbook")
    if asset_id not in spec.allowed_assets or side not in spec.allowed_sides:
        raise ValueError("route is not allowed by Family-B playbook")
    if reference.asset_id != asset_id:
        raise ValueError("frozen reference asset does not match replay route")
    expected_kind = expected_family_b_reference_kind(spec)
    if reference.kind is not expected_kind:
        raise ValueError("wrong frozen reference kind for Family-B playbook")
    if break_bar_close_utc.tzinfo is None:
        raise ValueError("break_bar_close_utc must be timezone-aware")

    rows = tuple(bars)
    if not rows:
        raise ValueError("closed replay bars are required")
    previous_close = None
    matches = []
    for index, bar in enumerate(rows):
        if bar.asset_id != asset_id:
            raise ValueError("all replay bars must share route asset_id")
        if bar.interval != spec.trigger_interval:
            raise ValueError("replay bar interval does not match playbook trigger")
        if bar.last_exchange_ts >= bar.bucket_close_utc:
            raise ValueError("forming bar cannot enter failed-break reconstruction")
        if previous_close is not None and bar.bucket_close_utc <= previous_close:
            raise ValueError("replay bar closes must be strictly ordered")
        previous_close = bar.bucket_close_utc
        if bar.bucket_close_utc == break_bar_close_utc:
            matches.append(index)
    if len(matches) != 1:
        raise ValueError("selected break bar must exist exactly once")

    break_index = matches[0]
    trigger_index = len(rows) - 1
    break_bar = rows[break_index]
    trigger_bar = rows[trigger_index]
    if reference.frozen_at_utc > break_bar.bucket_open_utc:
        raise ValueError("frozen reference was not available before break bar")

    if side == "short":
        break_printed = float(break_bar.close) > float(reference.high)
        close_back_inside = float(trigger_bar.close) < float(reference.high)
    else:
        break_printed = float(break_bar.close) < float(reference.low)
        close_back_inside = float(trigger_bar.close) > float(reference.low)

    return FamilyBReplayState(
        break_printed=break_printed,
        bars_since_break=trigger_index - break_index,
        close_back_inside=close_back_inside,
        counter_trend_condition=bool(counter_trend_condition),
        position_key_open=bool(position_key_open),
        locate_ok=locate_ok,
    )
