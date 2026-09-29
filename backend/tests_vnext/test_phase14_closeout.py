from __future__ import annotations

from pathlib import Path


PHASE14_MODULES = (
    "institutional_memory.py",
    "institutional_analogs.py",
    "institutional_memory_query.py",
    "pnl_attribution_rollup.py",
    "experience_archive.py",
    "experience_archive_store.py",
    "failure_history.py",
    "institutional_experience_context.py",
    "event_performance_matrix.py",
    "firm_review_surfaces.py",
    "change_ledger.py",
)

FORBIDDEN_AUTHORITY_IMPORTS = (
    "from aether_vnext.execution import",
    "from aether_vnext.risk import",
    "from aether_vnext.clerk import",
    "from aether_vnext.reservations import",
    "from aether_vnext.runtime_execution_bridge import",
    "from aether_vnext.runtime_risk_bridge import",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _module(name: str) -> str:
    return (_root() / "aether_vnext" / name).read_text(encoding="utf-8")


def test_phase14_source_tree_has_no_unresolved_implementation_markers() -> None:
    for name in PHASE14_MODULES:
        source = _module(name)
        assert "TODO" not in source, name
        assert "FIXME" not in source, name
        assert "NotImplemented" not in source, name


def test_phase14_modules_have_no_direct_execution_or_risk_mutation_imports() -> None:
    for name in PHASE14_MODULES:
        source = _module(name)
        for forbidden in FORBIDDEN_AUTHORITY_IMPORTS:
            assert forbidden not in source, (name, forbidden)


def test_phase14_point_in_time_queries_use_recorded_availability_cutoffs() -> None:
    memory_query = _module("institutional_memory_query.py")
    failure_query = _module("failure_history.py")
    crisis_query = _module("experience_archive_store.py")

    assert "table.c.recorded_at_utc <= query.as_of_utc" in memory_query
    assert "table.c.recorded_at_utc <= query.as_of_utc" in failure_query
    assert "table.c.recorded_at_utc <= query.as_of_utc" in crisis_query


def test_phase14_counterfactuals_cannot_become_independent_evidence() -> None:
    source = _module("institutional_memory.py")
    assert "hypothetical: bool = True" in source
    assert "independent_evidence_credit: bool = False" in source
    assert "counterfactual replay must remain hypothetical" in source
    assert (
        "counterfactual replay cannot receive independent evidence credit"
        in source
    )


def test_phase14_event_matrix_cannot_claim_causation_or_trade_authority() -> None:
    source = _module("event_performance_matrix.py")
    assert "association_only: bool = True" in source
    assert "causal_claim: bool = False" in source
    assert "trade_influence_allowed: bool = False" in source
    assert "independent_evidence_credit: bool = False" in source
    assert "event performance matrix cannot claim causation" in source


def test_phase14_daily_weekly_reviews_are_read_only_surfaces() -> None:
    source = _module("firm_review_surfaces.py")
    for required in (
        '"daily_firm_review"',
        '"weekly_firm_research_review"',
        '"read_only": True',
        '"execution_permission": False',
        '"may_create_orders": False',
        '"may_mutate_route_state": False',
        '"may_mutate_risk": False',
        '"may_reset_governor": False',
        '"may_award_independent_evidence_credit": False',
        '"automatic_promotion": False',
    ):
        assert required in source


def test_phase14_change_ledger_preserves_canonical_traceability_fields() -> None:
    source = _module("change_ledger.py")
    for required in (
        "change_id",
        "version",
        "timestamp",
        "section_changed",
        "reason",
        "logic_changed",
        "evidence_n_reset",
        "superseded_version_reference",
        "source_ref",
        "configuration_hash",
        "timestamp_utc",
    ):
        assert required in source


def test_phase14_schema_is_pinned_through_crisis_archive_revision_0031() -> None:
    facade = _module("schema.py")
    migration = (
        _root()
        / "alembic"
        / "versions"
        / "0031_aether_vnext_crisis_regime_archive.py"
    ).read_text(encoding="utf-8")
    assert "schema_v0031" in facade
    assert 'revision: str = "0031"' in migration
    assert 'down_revision: Union[str, None] = "0030"' in migration
    assert "trg_crisis_regime_archive_entries_immutable" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_phase14_document_change_ledger_uses_verified_commit_timestamps() -> None:
    ledger = (
        _root().parent / "docs" / "AETHER_PHASE14_CHANGE_LEDGER.md"
    ).read_text(encoding="utf-8")
    for required in (
        "Version",
        "Timestamp",
        "Section changed",
        "Reason",
        "logic_changed",
        "evidence n reset",
        "Superseded version/reference",
        "Commit / source ref",
        "63d3226f",
        "2026-09-29T12:50:13Z",
        "85152a6d",
        "2026-09-29T16:23:45Z",
        "ae1a8a67",
        "2026-09-29T16:27:55Z",
    ):
        assert required in ledger
