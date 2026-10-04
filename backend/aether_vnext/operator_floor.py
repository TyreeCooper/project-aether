"""Read-only Unified Firm Floor projection for AETHER vNext Phase 15.

Phase 15 is the New Operator UI / Floor. The Unified Firm Floor surface exposes
the full supported universe, caller-ranked Top 12 attention stations, canonical
seat queues, open-position cockpits, and one inspection drawer. It is a
projection only: PAPER ONLY, LIVE BLOCKED, and no second runtime or mutation
authority is introduced here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from datetime import datetime, timezone
import math
from typing import Any, Mapping


DOMINANT_STATES = frozenset(
    {
        "NO",
        "WATCH",
        "FIRE",
        "SIZE",
        "READY",
        "ORDER",
        "OPEN",
        "SEEING",
        "REJECT",
        "HALT",
    }
)

CANONICAL_SEAT_QUEUES = {
    "Scout": ("WATCH",),
    "Sniper": ("FIRE",),
    "Risk": ("SIZE", "REJECT"),
    "Clerk": ("READY", "REJECT"),
    "Portfolio": ("ORDER",),
    "Governor": ("HALT",),
}

CANONICAL_FIRM_SEATS = frozenset(
    {
        "Universe",
        "Scout",
        "Sniper",
        "Risk",
        "Clerk",
        "Portfolio",
        "Floor",
        "Exit",
        "Review",
        "Governor",
    }
)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _finite_optional(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite when present")
    return float(value)


@dataclass(frozen=True, slots=True)
class FloorUniverseStation:
    asset_id: str
    symbol: str
    product_type: str
    dominant_state: str
    seat_owner: str
    first_blocker: str | None
    first_blocker_reason: str | None
    mark: float | None
    open_position_count: int
    route_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("asset_id", "symbol", "product_type"):
            _text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.dominant_state not in DOMINANT_STATES:
            raise ValueError("invalid dominant_state")
        if self.seat_owner not in CANONICAL_FIRM_SEATS:
            raise ValueError("invalid seat_owner")
        if self.first_blocker is not None:
            _text("first_blocker", self.first_blocker)
        if self.first_blocker_reason is not None:
            _text("first_blocker_reason", self.first_blocker_reason)
        _finite_optional("mark", self.mark)
        if (
            not isinstance(self.open_position_count, int)
            or isinstance(self.open_position_count, bool)
            or self.open_position_count < 0
        ):
            raise ValueError("open_position_count must be a nonnegative integer")
        if not isinstance(self.route_ids, tuple):
            raise ValueError("route_ids must be an immutable tuple")
        for route_id in self.route_ids:
            _text("route_id", route_id)
        if len(self.route_ids) != len(set(self.route_ids)):
            raise ValueError("route_ids cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class AttentionStation:
    rank: int
    asset_id: str
    attention_basis_ref: str
    dominant_state: str
    seat_owner: str
    first_blocker: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rank, int)
            or isinstance(self.rank, bool)
            or not 1 <= self.rank <= 12
        ):
            raise ValueError("rank must be an integer in [1,12]")
        _text("asset_id", self.asset_id)
        _text("attention_basis_ref", self.attention_basis_ref)
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.dominant_state not in DOMINANT_STATES:
            raise ValueError("invalid dominant_state")
        if self.seat_owner not in CANONICAL_FIRM_SEATS:
            raise ValueError("invalid seat_owner")
        if self.first_blocker is not None:
            _text("first_blocker", self.first_blocker)


@dataclass(frozen=True, slots=True)
class SeatQueueSnapshot:
    seat: str
    state: str
    item_ids: tuple[str, ...]
    blocker_count: int = 0

    def __post_init__(self) -> None:
        if self.seat not in CANONICAL_SEAT_QUEUES:
            raise ValueError("seat is not a canonical Floor queue")
        if self.state not in CANONICAL_SEAT_QUEUES[self.seat]:
            raise ValueError("state is not owned by this seat queue")
        if not isinstance(self.item_ids, tuple):
            raise ValueError("item_ids must be an immutable tuple")
        for item_id in self.item_ids:
            _text("item_id", item_id)
        if len(self.item_ids) != len(set(self.item_ids)):
            raise ValueError("item_ids cannot contain duplicates")
        if (
            not isinstance(self.blocker_count, int)
            or isinstance(self.blocker_count, bool)
            or self.blocker_count < 0
        ):
            raise ValueError("blocker_count must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class OpenPositionCockpit:
    position_key: str
    trade_id: str
    asset_id: str
    horizon: str
    side: str
    quantity: float
    average_entry_price: float
    mark_price: float | None
    hard_stop_price: float
    opened_at_utc: datetime
    dominant_state: str = "OPEN"

    def __post_init__(self) -> None:
        for name in (
            "position_key",
            "trade_id",
            "asset_id",
            "horizon",
            "side",
        ):
            _text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.dominant_state not in {"OPEN", "SEEING"}:
            raise ValueError("open cockpit state must be OPEN or SEEING")
        for name in (
            "quantity",
            "average_entry_price",
            "hard_stop_price",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if float(self.quantity) <= 0.0:
            raise ValueError("quantity must be positive")
        _finite_optional("mark_price", self.mark_price)
        if self.opened_at_utc.tzinfo is None:
            raise ValueError("opened_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InspectionDrawer:
    asset_id: str
    station_ref: str
    market_observation_ref: str | None
    decision_lineage_ref: str | None
    evidence_refs: tuple[str, ...]
    blocker_refs: tuple[str, ...]
    read_only: bool = True

    def __post_init__(self) -> None:
        _text("asset_id", self.asset_id)
        _text("station_ref", self.station_ref)
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        for name in ("market_observation_ref", "decision_lineage_ref"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)
        for name in ("evidence_refs", "blocker_refs"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be an immutable tuple")
            for value in values:
                _text(f"{name} entry", value)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} cannot contain duplicates")
        if self.read_only is not True:
            raise ValueError("inspection drawer is read_only")


@dataclass(frozen=True, slots=True)
class UnifiedFirmFloorSnapshot:
    as_of_utc: datetime
    full_universe: tuple[FloorUniverseStation, ...]
    top12_attention: tuple[AttentionStation, ...]
    seat_queues: tuple[SeatQueueSnapshot, ...]
    open_cockpits: tuple[OpenPositionCockpit, ...]
    snapshot_id: str | None = None
    binding_state: str = "BOUND"
    paper_test_epoch_id: str | None = None
    paper_test_started_at_utc: datetime | None = None
    paper_test_seed_bank_usd: float | None = None
    paper_test_closed_trade_count: int = 0
    inspection_drawer: InspectionDrawer | None = None
    paper_only: bool = True
    live_blocked: bool = True

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if self.snapshot_id is not None:
            _text("snapshot_id", self.snapshot_id)
        if self.binding_state not in {"BOUND", "NOT_BOUND", "BASELINE_PENDING"}:
            raise ValueError("invalid binding_state")
        if self.paper_only is not True or self.live_blocked is not True:
            raise ValueError("Unified Firm Floor must remain PAPER ONLY / LIVE BLOCKED")
        if self.paper_test_epoch_id is not None:
            _text("paper_test_epoch_id", self.paper_test_epoch_id)
        if (
            self.paper_test_started_at_utc is not None
            and self.paper_test_started_at_utc.tzinfo is None
        ):
            raise ValueError("paper_test_started_at_utc must be timezone-aware")
        if self.paper_test_seed_bank_usd is not None:
            seed = _finite_optional(
                "paper_test_seed_bank_usd",
                self.paper_test_seed_bank_usd,
            )
            if seed is None or seed <= 0:
                raise ValueError("paper_test_seed_bank_usd must be positive")
        if (
            not isinstance(self.paper_test_closed_trade_count, int)
            or isinstance(self.paper_test_closed_trade_count, bool)
            or self.paper_test_closed_trade_count < 0
        ):
            raise ValueError(
                "paper_test_closed_trade_count must be a nonnegative integer"
            )

        asset_ids = tuple(row.asset_id for row in self.full_universe)
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("full_universe cannot contain duplicate assets")
        universe = set(asset_ids)

        attention_assets = tuple(row.asset_id for row in self.top12_attention)
        ranks = tuple(row.rank for row in self.top12_attention)
        if len(attention_assets) > 12:
            raise ValueError("top12_attention cannot exceed 12 assets")
        if len(attention_assets) != len(set(attention_assets)):
            raise ValueError("top12_attention cannot contain duplicate assets")
        if len(ranks) != len(set(ranks)):
            raise ValueError("top12_attention ranks must be unique")
        if not set(attention_assets) <= universe:
            raise ValueError("top12_attention assets must exist in full_universe")

        queue_keys = tuple((row.seat, row.state) for row in self.seat_queues)
        if len(queue_keys) != len(set(queue_keys)):
            raise ValueError("seat queue snapshots must be unique by seat/state")

        for cockpit in self.open_cockpits:
            if cockpit.asset_id not in universe:
                raise ValueError("open cockpit asset must exist in full_universe")
        position_keys = tuple(row.position_key for row in self.open_cockpits)
        if len(position_keys) != len(set(position_keys)):
            raise ValueError("open_cockpits cannot duplicate position_key")

        if (
            self.inspection_drawer is not None
            and self.inspection_drawer.asset_id not in universe
        ):
            raise ValueError("inspection drawer asset must exist in full_universe")


def build_unified_firm_floor(
    snapshot: UnifiedFirmFloorSnapshot,
) -> dict[str, object]:
    """Render the Phase-15 Floor contract without mutation authority."""
    def station(row: FloorUniverseStation) -> dict[str, object]:
        return {
            "asset_id": row.asset_id,
            "symbol": row.symbol,
            "product_type": row.product_type,
            "dominant_state": row.dominant_state,
            "seat_owner": row.seat_owner,
            "first_blocker": row.first_blocker,
            "first_blocker_reason": row.first_blocker_reason,
            "mark": row.mark,
            "open_position_count": row.open_position_count,
            "route_ids": list(row.route_ids),
        }

    refresh_time = snapshot.as_of_utc.astimezone(timezone.utc).isoformat()
    snapshot_id = snapshot.snapshot_id or hashlib.sha256(refresh_time.encode("utf-8")).hexdigest()[:24]
    bound = snapshot.binding_state == "BOUND"
    return {
        "snapshot_id": snapshot_id,
        "refresh_time_utc": refresh_time,
        "as_of_utc": refresh_time,
        "binding_state": snapshot.binding_state,
        "mode": {
            "paper_only": True,
            "live_blocked": True,
        },
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "may_mutate_firm_state": False,
            "second_runtime": False,
        },
        "paper_test": {
            "epoch_id": snapshot.paper_test_epoch_id if bound else None,
            "started_at_utc": (
                None
                if snapshot.paper_test_started_at_utc is None
                else snapshot.paper_test_started_at_utc.astimezone(
                    timezone.utc
                ).isoformat()
            ),
            "seed_bank_usd": snapshot.paper_test_seed_bank_usd if bound else None,
            "blotter_trade_count": snapshot.paper_test_closed_trade_count if bound else None,
        },
        "full_universe": [station(row) for row in snapshot.full_universe],
        "top12_attention": [
            {
                "rank": row.rank,
                "asset_id": row.asset_id,
                "attention_basis_ref": row.attention_basis_ref,
                "dominant_state": row.dominant_state,
                "seat_owner": row.seat_owner,
                "first_blocker": row.first_blocker,
            }
            for row in sorted(snapshot.top12_attention, key=lambda item: item.rank)
        ],
        "seat_queues": [
            {
                "seat": row.seat,
                "state": row.state,
                "item_ids": list(row.item_ids),
                "count": len(row.item_ids),
                "blocker_count": row.blocker_count,
            }
            for row in snapshot.seat_queues
        ],
        "open_cockpits": [
            {
                "position_key": row.position_key,
                "trade_id": row.trade_id,
                "asset_id": row.asset_id,
                "horizon": row.horizon,
                "side": row.side,
                "quantity": row.quantity,
                "average_entry_price": row.average_entry_price,
                "mark_price": row.mark_price,
                "hard_stop_price": row.hard_stop_price,
                "opened_at_utc": row.opened_at_utc.astimezone(timezone.utc).isoformat(),
                "dominant_state": row.dominant_state,
            }
            for row in snapshot.open_cockpits
        ],
        "inspection_drawer": (
            None
            if snapshot.inspection_drawer is None
            else {
                "asset_id": snapshot.inspection_drawer.asset_id,
                "station_ref": snapshot.inspection_drawer.station_ref,
                "market_observation_ref": snapshot.inspection_drawer.market_observation_ref,
                "decision_lineage_ref": snapshot.inspection_drawer.decision_lineage_ref,
                "evidence_refs": list(snapshot.inspection_drawer.evidence_refs),
                "blocker_refs": list(snapshot.inspection_drawer.blocker_refs),
                "read_only": True,
            }
        ),
    }
