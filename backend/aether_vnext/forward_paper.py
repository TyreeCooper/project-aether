"""Forward-paper evidence campaign ledger.

C9.1 defines operating invariants, not a frozen ForwardPaperCampaign object. This
module is therefore a minimal implementation ledger around the already-frozen
EvidenceWindow domain. It adds no trading rule, signal override, or live capability.

Paper-forward evidence must come from natural paper trading and remain separate from
historical validation and execution-validation evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ForwardPaperCampaign:
    campaign_id: str
    configuration_hash: str
    policy_version: str
    baseline_snapshot_hash: str
    started_at_utc: datetime
    created_at_utc: datetime
    forced_entry_enabled: bool = False
    natural_setup_only: bool = True
    real_market_time_required: bool = True
    pit_inputs_required: bool = True
    modeled_cost_capture_required: bool = True
    observed_cost_capture_required: bool = True
    route_pnl_accounting_required: bool = True
    disposition_accounting_required: bool = True
    no_cherry_pick: bool = True
    historical_comparison_separate: bool = True
    live_blocked: bool = True

    def __post_init__(self) -> None:
        for name in (
            "campaign_id",
            "configuration_hash",
            "policy_version",
            "baseline_snapshot_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        for name in ("started_at_utc", "created_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.started_at_utc > self.created_at_utc:
            raise ValueError("campaign cannot start after its durable creation time")

        required_true = (
            "natural_setup_only",
            "real_market_time_required",
            "pit_inputs_required",
            "modeled_cost_capture_required",
            "observed_cost_capture_required",
            "route_pnl_accounting_required",
            "disposition_accounting_required",
            "no_cherry_pick",
            "historical_comparison_separate",
            "live_blocked",
        )
        if self.forced_entry_enabled:
            raise ValueError("forward-paper campaign requires forced entry OFF")
        for name in required_true:
            if getattr(self, name) is not True:
                raise ValueError(f"forward-paper campaign requires {name}=true")


@dataclass(frozen=True, slots=True)
class ForwardPaperRouteBaseline:
    campaign_route_id: str
    campaign_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    configuration_hash: str
    runtime_registry_binding_hash: str
    historical_validation_window_ids: tuple[str, ...]
    historical_metrics_snapshot_hash: str

    def __post_init__(self) -> None:
        for name in (
            "campaign_route_id",
            "campaign_id",
            "route_id",
            "playbook_id",
            "playbook_version",
            "configuration_hash",
            "runtime_registry_binding_hash",
            "historical_metrics_snapshot_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        window_ids = tuple(
            str(value).strip()
            for value in self.historical_validation_window_ids
        )
        if not window_ids or any(not value for value in window_ids):
            raise ValueError(
                "historical_validation_window_ids must contain nonblank IDs"
            )
        if len(window_ids) != len(set(window_ids)):
            raise ValueError(
                "historical_validation_window_ids cannot contain duplicates"
            )


def parse_route_id(route_id: str) -> tuple[str, str, str]:
    parts = tuple(str(route_id).split(":"))
    if len(parts) != 3 or any(not part for part in parts):
        raise ValueError("route_id must be asset:horizon:side")
    asset_id, horizon, side = parts
    if side not in {"long", "short"}:
        raise ValueError("route_id side must be long or short")
    return asset_id, horizon, side
