from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.intelligence_audit import (
    IntelligenceShadowAudit,
    summarize_shadow_audits,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 8, 30, tzinfo=UTC)


def _audit(
    *,
    audit_id: str = "audit-1",
    enabled_components: tuple[str, ...] = ("macro",),
    baseline_outcome: str = "WATCH",
    shadow_outcome: str = "WATCH",
    research_only: bool = True,
    order_created: bool = False,
    trade_influence_enabled: bool = False,
) -> IntelligenceShadowAudit:
    return IntelligenceShadowAudit(
        audit_id=audit_id,
        opportunity_id="opp-1",
        route_id="btc:intraday:pb-test",
        as_of_utc=T0,
        baseline_configuration_hash="baseline-hash",
        shadow_configuration_hash="shadow-hash",
        enabled_components=enabled_components,
        baseline_outcome=baseline_outcome,
        shadow_outcome=shadow_outcome,
        evidence_ids=("event-1", "health-1"),
        research_only=research_only,
        order_created=order_created,
        trade_influence_enabled=trade_influence_enabled,
    )


def test_shadow_audit_records_outcome_change_without_alpha_claim() -> None:
    unchanged = _audit()
    changed = _audit(
        audit_id="audit-2",
        baseline_outcome="WATCH",
        shadow_outcome="HIDE",
    )

    assert unchanged.outcome_changed is False
    assert changed.outcome_changed is True

    summary = summarize_shadow_audits(
        (unchanged, changed),
        enabled_components=("macro",),
    )
    assert summary["observations"] == 2
    assert summary["outcome_changed_count"] == 1
    assert summary["outcome_unchanged_count"] == 1
    assert summary["alpha_claim"] is None
    assert summary["trade_influence_enabled"] is False


def test_shadow_summary_is_component_cohort_exact() -> None:
    macro = _audit(audit_id="audit-macro", enabled_components=("macro",))
    news = _audit(audit_id="audit-news", enabled_components=("news",))

    summary = summarize_shadow_audits(
        (macro, news),
        enabled_components=("macro",),
    )
    assert summary["observations"] == 1


def test_shadow_audit_requires_canonical_sorted_unique_components() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        _audit(enabled_components=("news", "macro"))

    with pytest.raises(ValueError, match="must be unique"):
        _audit(enabled_components=("macro", "macro"))

    with pytest.raises(ValueError, match="unknown intelligence components"):
        _audit(enabled_components=("macro", "unknown"))


def test_shadow_audit_requires_distinct_configuration_hashes() -> None:
    with pytest.raises(ValueError, match="distinct configuration hashes"):
        IntelligenceShadowAudit(
            audit_id="audit-1",
            opportunity_id="opp-1",
            route_id="btc:intraday:pb-test",
            as_of_utc=T0,
            baseline_configuration_hash="same",
            shadow_configuration_hash="same",
            enabled_components=("macro",),
            baseline_outcome="WATCH",
            shadow_outcome="WATCH",
            evidence_ids=(),
        )


def test_shadow_audit_cannot_gain_execution_authority() -> None:
    with pytest.raises(
        ValueError,
        match="intelligence shadow audit is research_only",
    ):
        _audit(research_only=False)

    with pytest.raises(
        ValueError,
        match="intelligence shadow audit cannot create orders",
    ):
        _audit(order_created=True)

    with pytest.raises(
        ValueError,
        match="cannot enable trade influence",
    ):
        _audit(trade_influence_enabled=True)


def test_shadow_audit_requires_aware_time_and_immutable_evidence() -> None:
    with pytest.raises(ValueError, match="as_of_utc must be timezone-aware"):
        IntelligenceShadowAudit(
            audit_id="audit-1",
            opportunity_id="opp-1",
            route_id="btc:intraday:pb-test",
            as_of_utc=T0.replace(tzinfo=None),
            baseline_configuration_hash="baseline-hash",
            shadow_configuration_hash="shadow-hash",
            enabled_components=("macro",),
            baseline_outcome="WATCH",
            shadow_outcome="WATCH",
            evidence_ids=(),
        )

    with pytest.raises(ValueError, match="evidence_ids must be an immutable tuple"):
        IntelligenceShadowAudit(
            audit_id="audit-1",
            opportunity_id="opp-1",
            route_id="btc:intraday:pb-test",
            as_of_utc=T0,
            baseline_configuration_hash="baseline-hash",
            shadow_configuration_hash="shadow-hash",
            enabled_components=("macro",),
            baseline_outcome="WATCH",
            shadow_outcome="WATCH",
            evidence_ids=["event-1"],
        )
