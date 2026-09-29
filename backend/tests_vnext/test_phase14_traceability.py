from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.change_ledger import ChangeLedgerEntry, build_change_ledger
from aether_vnext.firm_review_surfaces import (
    DailyFirmReviewInput,
    build_daily_firm_review,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)


def _daily(timestamp: datetime) -> DailyFirmReviewInput:
    return DailyFirmReviewInput(
        review_timestamp=timestamp,
        operator_timezone="America/New_York",
        market_event_regimes=(),
        material_news_events_and_analogs=(),
        opportunities_and_dispositions=(),
        trades_opened_closed_duration=(),
        pnl_and_cost_drag={},
        blocked_opportunities=(),
        route_evidence_increments=(),
        abnormal_execution_reconciliation=(),
        risk_utilization_and_cluster_exposure={},
        route_state_changes=(),
    )


def test_firm_review_uses_canonical_utc_and_operator_local_timestamp() -> None:
    local = datetime(2026, 9, 29, 14, 0, tzinfo=timezone(timedelta(hours=-4)))
    result = build_daily_firm_review(_daily(local))

    assert result["review_timestamp"] == "2026-09-29T18:00:00+00:00"
    assert result["operator_timezone"] == "America/New_York"
    assert result["review_timestamp_local"].startswith("2026-09-29T14:00:00")


def test_change_ledger_preserves_exact_c9_5_fields_and_lineage() -> None:
    entry = ChangeLedgerEntry(
        change_id="change-14-001",
        version="phase14-v1",
        timestamp=T0,
        section_changed="C9.2",
        reason="add daily Firm review projection",
        logic_changed=False,
        evidence_n_reset=False,
        superseded_version_reference=None,
        source_ref="AETHER-v1.4-C9.2",
        configuration_hash="cfg-phase14",
    )

    result = build_change_ledger((entry,))

    assert result == (
        {
            "change_id": "change-14-001",
            "version": "phase14-v1",
            "timestamp": T0.isoformat(),
            "section_changed": "C9.2",
            "reason": "add daily Firm review projection",
            "logic_changed": False,
            "evidence_n_reset": False,
            "superseded_version_reference": None,
            "source_ref": "AETHER-v1.4-C9.2",
            "configuration_hash": "cfg-phase14",
            "authority": {
                "read_only": True,
                "execution_permission": False,
                "may_award_independent_evidence_credit": False,
            },
        },
    )


def test_change_ledger_rejects_duplicate_change_identity() -> None:
    entry = ChangeLedgerEntry(
        change_id="change-1",
        version="v1",
        timestamp=T0,
        section_changed="C9.5",
        reason="traceability",
        logic_changed=False,
        evidence_n_reset=False,
        superseded_version_reference=None,
        source_ref="source",
        configuration_hash="cfg",
    )
    with pytest.raises(ValueError, match="change_id must be unique"):
        build_change_ledger((entry, entry))


def test_operator_timezone_must_be_valid_iana_timezone() -> None:
    with pytest.raises(ValueError, match="valid IANA timezone"):
        DailyFirmReviewInput(
            review_timestamp=T0,
            operator_timezone="Not/A_Zone",
            market_event_regimes=(),
            material_news_events_and_analogs=(),
            opportunities_and_dispositions=(),
            trades_opened_closed_duration=(),
            pnl_and_cost_drag={},
            blocked_opportunities=(),
            route_evidence_increments=(),
            abnormal_execution_reconciliation=(),
            risk_utilization_and_cluster_exposure={},
            route_state_changes=(),
        )
