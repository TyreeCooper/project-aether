from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.institutional_memory import (
    PnlAttributionComponent,
    PnlAttributionRecord,
)
from aether_vnext.pnl_attribution_rollup import (
    PnlAttributionRollup,
    PnlAttributionRollupKey,
    rollup_pnl_attributions,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)


def _record(
    attribution_id: str,
    *,
    net: float,
    fees: float,
    mechanism_id: str = "trend",
    regime_id: str = "trend-up",
    minute: int = 0,
) -> PnlAttributionRecord:
    alpha = net - fees
    return PnlAttributionRecord(
        attribution_id=attribution_id,
        firm_id="aether",
        mechanism_id=mechanism_id,
        playbook_id="pb-trend",
        playbook_version="v1",
        route_id="btc:1h:trend",
        asset_id="btc",
        horizon="1h",
        side="long",
        regime_id=regime_id,
        trade_id=f"trade-{attribution_id}",
        configuration_hash="cfg-1",
        net_pnl_usd=net,
        components=(
            PnlAttributionComponent("alpha", alpha),
            PnlAttributionComponent("fees", fees),
        ),
        attributed_at_utc=T0 + timedelta(minutes=minute),
        source_record_ids=(f"trade-{attribution_id}",),
    )


def test_rollup_is_descriptive_and_reconciles_components() -> None:
    first = _record("attr-1", net=90.0, fees=-10.0, minute=1)
    second = _record("attr-2", net=-20.0, fees=-5.0, minute=2)

    result = rollup_pnl_attributions((second, first))

    assert len(result) == 1
    rollup = result[0]
    assert rollup.trade_count == 2
    assert rollup.net_pnl_usd == 70.0
    assert rollup.attribution_ids == ("attr-1", "attr-2")
    assert {row.category: row.amount_usd for row in rollup.components} == {
        "alpha": 85.0,
        "fees": -15.0,
    }
    assert rollup.descriptive_only is True
    assert rollup.trade_influence_allowed is False
    assert rollup.independent_evidence_credit is False


def test_rollup_keeps_mechanism_and_regime_lineage_separate() -> None:
    trend = _record("trend-1", net=10.0, fees=-1.0)
    failed_break = _record(
        "failed-1",
        net=8.0,
        fees=-2.0,
        mechanism_id="failed-break",
        regime_id="range",
    )

    result = rollup_pnl_attributions((failed_break, trend))

    assert len(result) == 2
    assert {row.key.mechanism_id for row in result} == {
        "failed-break",
        "trend",
    }


def test_rollup_rejects_duplicate_attribution_identity() -> None:
    record = _record("attr-1", net=10.0, fees=-1.0)
    with pytest.raises(ValueError, match="duplicate attribution_id"):
        rollup_pnl_attributions((record, record))


def test_rollup_boundary_cannot_be_promoted_to_trade_authority() -> None:
    key = PnlAttributionRollupKey(
        firm_id="aether",
        mechanism_id="trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        route_id="btc:1h:trend",
        asset_id="btc",
        horizon="1h",
        side="long",
        regime_id="trend-up",
        configuration_hash="cfg-1",
    )
    components = (PnlAttributionComponent("alpha", 1.0),)

    with pytest.raises(ValueError, match="cannot influence trades"):
        PnlAttributionRollup(
            key=key,
            trade_count=1,
            net_pnl_usd=1.0,
            components=components,
            first_attributed_at_utc=T0,
            last_attributed_at_utc=T0,
            attribution_ids=("attr-1",),
            trade_influence_allowed=True,
        )
