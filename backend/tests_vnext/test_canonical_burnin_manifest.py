from __future__ import annotations

from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_coverage_requests,
    canonical_forward_paper_manifest,
    canonical_forward_paper_route_requests,
)
from aether_vnext.playbook_exits import exit_rule
from aether_vnext.playbooks import ordered_playbooks, playbook


def test_canonical_burnin_manifest_preserves_coverage_and_executable_subset() -> None:
    manifest = canonical_forward_paper_manifest()
    coverage = manifest.coverage_requests
    executable = manifest.executable_requests

    assert manifest.coverage_route_count == 79
    assert manifest.executable_route_count == 74
    assert manifest.excluded_route_count == 5
    assert coverage == canonical_forward_paper_coverage_requests()
    assert executable == canonical_forward_paper_route_requests()

    coverage_keys = {(row.route_id, row.playbook_id) for row in coverage}
    executable_keys = {(row.route_id, row.playbook_id) for row in executable}
    assert len(coverage_keys) == len(coverage)
    assert len(executable_keys) == len(executable)
    assert executable_keys < coverage_keys

    expected_coverage = set()
    for spec in ordered_playbooks():
        if not spec.scout_definition_enabled:
            continue
        for asset_id, side, horizon in spec.route_tuples():
            expected_coverage.add(
                (f"{asset_id}:{horizon}:{side}", spec.playbook_id)
            )
    assert coverage_keys == expected_coverage

    for request in executable:
        assert playbook(request.playbook_id).scout_definition_enabled is True
        assert exit_rule(request.playbook_id).source_complete is True


def test_canonical_burnin_exclusions_are_visible_not_silently_dropped() -> None:
    manifest = canonical_forward_paper_manifest()
    excluded = {
        (row.request.route_id, row.request.playbook_id)
        for row in manifest.exclusions
    }
    assert excluded == {
        ("eth:daily_swing:long", "pb_eth_rider_v1_2"),
        ("eurusd:intraday:long", "pb_fx_range_v1_3"),
        ("eurusd:intraday:short", "pb_fx_range_v1_3"),
        ("nvda:intraday:long", "pb_eq_range_v1_3"),
        ("nvda:intraday:short", "pb_eq_range_v1_3"),
    }
    assert all(row.reason for row in manifest.exclusions)


def test_canonical_burnin_requests_exclude_benched_disabled_and_incomplete() -> None:
    ids = {row.playbook_id for row in canonical_forward_paper_route_requests()}
    assert "pb_fx_scalp_v1_2" not in ids
    assert "pb_crypto_failed_break_v1_3" not in ids
    assert "pb_eth_failed_break_v1_3" not in ids
    assert "pb_eth_rider_v1_2" not in ids
    assert "pb_fx_range_v1_3" not in ids
    assert "pb_eq_range_v1_3" not in ids
