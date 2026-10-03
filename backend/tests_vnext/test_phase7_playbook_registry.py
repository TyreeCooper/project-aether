from __future__ import annotations

from datetime import timedelta

from aether_vnext.freeze import (
    CRYPTO_SHORT_DISABLED_PLAYBOOKS,
    EvidenceState,
    OperationalState,
    ResearchState,
)
from aether_vnext.playbooks import (
    PLAYBOOK_REGISTRY,
    PlaybookFamily,
    canonical_playbook_ids,
    ordered_playbooks,
    playbook,
    playbooks_for,
)


EXPECTED_IDS = {
    "pb_crypto_swing_v1_2",
    "pb_eth_rider_v1_2",
    "pb_fx_intraday_v1_2",
    "pb_fx_swing_v1_2",
    "pb_fx_scalp_v1_2",
    "pb_idx_scalp_v1_2",
    "pb_idx_intraday_v1_2",
    "pb_idx_swing_v1_2",
    "pb_metal_intraday_v1_2",
    "pb_metal_swing_v1_2",
    "pb_energy_intraday_v1_2",
    "pb_energy_swing_v1_2",
    "pb_rates_swing_v1_2",
    "pb_eq_scalp_v1_2",
    "pb_eq_intraday_v1_2",
    "pb_eq_swing_v1_2",
    "pb_crypto_failed_break_v1_3",
    "pb_eth_failed_break_v1_3",
    "pb_fx_failed_session_v1_3",
    "pb_fx_failed_swing_v1_3",
    "pb_idx_failed_v1_3",
    "pb_metal_failed_v1_3",
    "pb_energy_failed_v1_3",
    "pb_rates_failed_v1_3",
    "pb_eq_failed_v1_3",
    "pb_fx_range_v1_3",
    "pb_eq_range_v1_3",
}


def test_registry_contains_exact_bound_27_playbook_files() -> None:
    assert len(PLAYBOOK_REGISTRY) == 27
    assert set(PLAYBOOK_REGISTRY) == EXPECTED_IDS
    assert len(canonical_playbook_ids()) == 27


def test_family_counts_match_bound_playbook_pack() -> None:
    counts = {
        family: sum(1 for row in PLAYBOOK_REGISTRY.values() if row.family is family)
        for family in PlaybookFamily
    }
    assert counts == {
        PlaybookFamily.A: 16,
        PlaybookFamily.B: 9,
        PlaybookFamily.C: 2,
    }


def test_evidence_status_count_is_26_candidate_plus_one_bench() -> None:
    candidates = [
        row
        for row in PLAYBOOK_REGISTRY.values()
        if row.evidence_state is EvidenceState.CANDIDATE
    ]
    benches = [
        row
        for row in PLAYBOOK_REGISTRY.values()
        if row.evidence_state is EvidenceState.BENCH
    ]
    assert len(candidates) == 26
    assert [row.playbook_id for row in benches] == ["pb_fx_scalp_v1_2"]
    assert benches[0].scout_definition_enabled is False


def test_all_bound_playbooks_are_frozen_research_definitions() -> None:
    assert {
        row.research_state for row in PLAYBOOK_REGISTRY.values()
    } == {ResearchState.FROZEN}


def test_family_precedence_is_a_then_b_then_c() -> None:
    ordered = ordered_playbooks(
        [
            playbook("pb_fx_range_v1_3"),
            playbook("pb_fx_failed_session_v1_3"),
            playbook("pb_fx_intraday_v1_2"),
        ]
    )
    assert [row.family for row in ordered] == [
        PlaybookFamily.A,
        PlaybookFamily.B,
        PlaybookFamily.C,
    ]


def test_trigger_intervals_are_explicit_not_derived_from_horizon() -> None:
    assert playbook("pb_fx_scalp_v1_2").trigger_interval == timedelta(minutes=1)
    assert playbook("pb_idx_scalp_v1_2").trigger_interval == timedelta(minutes=15)
    assert playbook("pb_crypto_swing_v1_2").trigger_interval == timedelta(hours=1)
    assert playbook("pb_eq_swing_v1_2").trigger_interval == timedelta(minutes=15)


def test_precode_crypto_short_override_preserves_definition_but_disables_operation() -> None:
    assert CRYPTO_SHORT_DISABLED_PLAYBOOKS == {
        "pb_crypto_failed_break_v1_3",
        "pb_eth_failed_break_v1_3",
    }
    for playbook_id in CRYPTO_SHORT_DISABLED_PLAYBOOKS:
        row = playbook(playbook_id)
        assert row.evidence_state is EvidenceState.CANDIDATE
        assert row.research_state is ResearchState.FROZEN
        assert row.operational_state is OperationalState.DISABLED
        assert row.scout_definition_enabled is False


def test_default_lookup_excludes_benched_and_operationally_disabled_files() -> None:
    btc_short = playbooks_for(
        asset_id="btc",
        horizon="daily_swing",
        side="short",
    )
    assert btc_short == ()

    btc_short_defined = playbooks_for(
        asset_id="btc",
        horizon="daily_swing",
        side="short",
        include_operationally_disabled=True,
    )
    assert [row.playbook_id for row in btc_short_defined] == [
        "pb_crypto_failed_break_v1_3"
    ]

    fx_scalp = playbooks_for(
        asset_id="eurusd",
        horizon="scalp",
        side="long",
    )
    assert fx_scalp == ()

    fx_scalp_defined = playbooks_for(
        asset_id="eurusd",
        horizon="scalp",
        side="long",
        include_benched=True,
    )
    assert [row.playbook_id for row in fx_scalp_defined] == [
        "pb_fx_scalp_v1_2"
    ]


def test_route_tuple_cardinality_matches_bound_file_metadata() -> None:
    assert sum(
        len(row.route_tuples()) for row in PLAYBOOK_REGISTRY.values()
    ) == 85


def test_registry_uses_no_legacy_runtime_imports() -> None:
    import inspect
    import aether_vnext.playbooks as module

    source = inspect.getsource(module)
    assert "from app" not in source
    assert "import app" not in source
