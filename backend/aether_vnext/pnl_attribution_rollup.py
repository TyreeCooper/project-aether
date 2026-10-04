"""Descriptive P&L attribution rollups for AETHER vNext institutional memory."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable

from aether_vnext.institutional_memory import (
    PnlAttributionComponent,
    PnlAttributionRecord,
)


@dataclass(frozen=True, slots=True, order=True)
class PnlAttributionRollupKey:
    firm_id: str
    mechanism_id: str
    playbook_id: str
    playbook_version: str
    route_id: str
    asset_id: str
    horizon: str
    side: str
    regime_id: str
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class PnlAttributionRollup:
    key: PnlAttributionRollupKey
    trade_count: int
    net_pnl_usd: float
    components: tuple[PnlAttributionComponent, ...]
    first_attributed_at_utc: datetime
    last_attributed_at_utc: datetime
    attribution_ids: tuple[str, ...]
    descriptive_only: bool = True
    trade_influence_allowed: bool = False
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        if self.trade_count <= 0:
            raise ValueError("trade_count must be positive")
        if self.first_attributed_at_utc.tzinfo is None:
            raise ValueError("first_attributed_at_utc must be timezone-aware")
        if self.last_attributed_at_utc.tzinfo is None:
            raise ValueError("last_attributed_at_utc must be timezone-aware")
        if self.last_attributed_at_utc < self.first_attributed_at_utc:
            raise ValueError("rollup attribution time range is reversed")
        if len(self.attribution_ids) != self.trade_count:
            raise ValueError("attribution_ids must align with trade_count")
        if len(self.attribution_ids) != len(set(self.attribution_ids)):
            raise ValueError("attribution_ids cannot contain duplicates")
        if self.descriptive_only is not True:
            raise ValueError("P&L attribution rollup is descriptive_only")
        if self.trade_influence_allowed is not False:
            raise ValueError("P&L attribution rollup cannot influence trades")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "P&L attribution rollup cannot receive independent evidence credit"
            )
        component_total = math.fsum(row.amount_usd for row in self.components)
        if not math.isclose(
            component_total,
            self.net_pnl_usd,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("rollup components must reconcile to net P&L")


def _key(record: PnlAttributionRecord) -> PnlAttributionRollupKey:
    return PnlAttributionRollupKey(
        firm_id=record.firm_id,
        mechanism_id=record.mechanism_id,
        playbook_id=record.playbook_id,
        playbook_version=record.playbook_version,
        route_id=record.route_id,
        asset_id=record.asset_id,
        horizon=record.horizon,
        side=record.side,
        regime_id=record.regime_id,
        configuration_hash=record.configuration_hash,
    )


def rollup_pnl_attributions(
    records: Iterable[PnlAttributionRecord],
) -> tuple[PnlAttributionRollup, ...]:
    """Aggregate immutable attribution records without ranking or policy weights."""
    grouped: dict[PnlAttributionRollupKey, list[PnlAttributionRecord]] = {}
    seen_ids: set[str] = set()

    for record in records:
        if record.attribution_id in seen_ids:
            raise ValueError("duplicate attribution_id in rollup input")
        seen_ids.add(record.attribution_id)
        grouped.setdefault(_key(record), []).append(record)

    output: list[PnlAttributionRollup] = []
    for key in sorted(grouped):
        rows = sorted(
            grouped[key],
            key=lambda row: (row.attributed_at_utc, row.attribution_id),
        )
        categories = sorted(
            {
                component.category
                for row in rows
                for component in row.components
            }
        )
        components = tuple(
            PnlAttributionComponent(
                category=category,
                amount_usd=math.fsum(
                    component.amount_usd
                    for row in rows
                    for component in row.components
                    if component.category == category
                ),
            )
            for category in categories
        )
        output.append(
            PnlAttributionRollup(
                key=key,
                trade_count=len(rows),
                net_pnl_usd=math.fsum(row.net_pnl_usd for row in rows),
                components=components,
                first_attributed_at_utc=rows[0].attributed_at_utc,
                last_attributed_at_utc=rows[-1].attributed_at_utc,
                attribution_ids=tuple(row.attribution_id for row in rows),
            )
        )

    return tuple(output)
