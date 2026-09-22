import pytest

from app.asset_sources import merge_source_registry, registry_summary, set_trust_state


def test_seeded_community_source_starts_candidate_not_trusted():
    rows = merge_source_registry([], ["btc"])
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "btc"
    assert rows[0]["trust_state"] == "candidate"
    assert rows[0]["trade_influence_enabled"] is False


def test_operator_trust_state_is_explicit_and_preserved():
    rows = merge_source_registry([], ["eth"])
    source_id = rows[0]["source_id"]
    changed = set_trust_state(rows, source_id, "trusted")
    assert changed[0]["trust_state"] == "trusted"
    assert registry_summary(changed)["trust_states"]["trusted"] == 1


def test_invalid_trust_state_fails_closed():
    rows = merge_source_registry([], ["btc"])
    assert rows
    with pytest.raises(ValueError):
        set_trust_state(rows, rows[0]["source_id"], "auto_buy")
