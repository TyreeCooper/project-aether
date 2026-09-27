from __future__ import annotations

from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_route_requests,
)
from aether_vnext.playbooks import playbook


def test_canonical_burnin_requests_are_complete_unique_and_eligible() -> None:
    requests = canonical_forward_paper_route_requests()
    assert requests
    keys = {(row.route_id, row.playbook_id) for row in requests}
    assert len(keys) == len(requests)

    expected = set()
    for playbook_id in {row.playbook_id for row in requests}:
        spec = playbook(playbook_id)
        assert spec.scout_definition_enabled is True

    from aether_vnext.playbooks import ordered_playbooks

    for spec in ordered_playbooks():
        if not spec.scout_definition_enabled:
            continue
        for asset_id, side, horizon in spec.route_tuples():
            expected.add(
                (f"{asset_id}:{horizon}:{side}", spec.playbook_id)
            )

    assert keys == expected


def test_canonical_burnin_requests_exclude_benched_and_disabled_playbooks() -> None:
    ids = {row.playbook_id for row in canonical_forward_paper_route_requests()}
    assert "pb_fx_scalp_v1_2" not in ids
    assert "pb_crypto_failed_break_v1_3" not in ids
    assert "pb_eth_failed_break_v1_3" not in ids
