"""Point-in-time regime tags for AETHER profitability evidence.

The Master binds six minimum regime families on every new Setup and ClosedTrade.
Labels remain open strings because the source binds the dimensions, not one global
taxonomy across every product.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RegimeTags:
    trend_range: str
    realized_volatility_band: str
    session: str
    spread_cost_band: str
    event_risk_state: str
    data_quality_state: str
    as_of_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "trend_range",
            "realized_volatility_band",
            "session",
            "spread_cost_band",
            "event_risk_state",
            "data_quality_state",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")

    def assert_point_in_time(self, *, no_later_than_utc: datetime) -> None:
        if no_later_than_utc.tzinfo is None:
            raise ValueError("no_later_than_utc must be timezone-aware")
        if self.as_of_utc > no_later_than_utc:
            raise ValueError("regime tags contain future information")

    def to_payload(self) -> dict[str, str]:
        return {
            "trend_range": self.trend_range,
            "realized_volatility_band": self.realized_volatility_band,
            "session": self.session,
            "spread_cost_band": self.spread_cost_band,
            "event_risk_state": self.event_risk_state,
            "data_quality_state": self.data_quality_state,
            "as_of_utc": self.as_of_utc.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RegimeTags":
        if not payload:
            raise ValueError("regime_tags are required")
        raw_ts = payload.get("as_of_utc")
        if isinstance(raw_ts, datetime):
            ts = raw_ts
        else:
            if not str(raw_ts or "").strip():
                raise ValueError("regime_tags.as_of_utc is required")
            ts = datetime.fromisoformat(str(raw_ts))
        return cls(
            trend_range=str(payload.get("trend_range") or ""),
            realized_volatility_band=str(
                payload.get("realized_volatility_band") or ""
            ),
            session=str(payload.get("session") or ""),
            spread_cost_band=str(payload.get("spread_cost_band") or ""),
            event_risk_state=str(payload.get("event_risk_state") or ""),
            data_quality_state=str(payload.get("data_quality_state") or ""),
            as_of_utc=ts,
        )
