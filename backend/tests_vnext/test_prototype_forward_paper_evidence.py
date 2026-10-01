from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.prototype_forward_paper_evidence import (
    AGGREGATE_TYPE,
    SAMPLE_DOMAIN,
    count_prototype_no_setup_observations,
    persist_prototype_no_setup_observation,
    prototype_strategy_observation_event_id,
)
from aether_vnext.store import VNextStore
from tests_vnext.test_prototype_crypto_entry_runtime import _obs


UTC = timezone.utc
T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


def _store_fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    observation = _obs("obs-forward-paper-no-setup", T0 + timedelta(seconds=2))
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="prototype-paper-policy-v1",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="prototype forward-paper observation",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, observation)
    return engine, store, observation


def test_no_setup_observation_is_immutable_idempotent_and_non_phase18() -> None:
    engine, store, observation = _store_fixture()
    kwargs = dict(
        paper_epoch_id="aether-prototype-new-system-test-001",
        asset_id="btc",
        trigger_close_utc=T0,
        evaluated_at_utc=T0 + timedelta(seconds=3),
        market_observation_id=observation.observation_id,
        reason="structure_fail",
        watch_eligible=False,
        volatility_percentile=91.94,
        setup_id="setup-prototype-btc-test",
        ticket_id="ticket-prototype-btc-test",
        order_intent_id="intent-prototype-btc-test",
    )

    with engine.begin() as conn:
        assert persist_prototype_no_setup_observation(conn, store, **kwargs) is True
        assert persist_prototype_no_setup_observation(conn, store, **kwargs) is False
        assert count_prototype_no_setup_observations(
            conn,
            store,
            paper_epoch_id="aether-prototype-new-system-test-001",
        ) == 1

        rows = tuple(
            conn.execute(
                sa.select(store.tables["event_ledger"]).where(
                    store.tables["event_ledger"].c.aggregate_type == AGGREGATE_TYPE
                )
            ).mappings()
        )

    assert len(rows) == 1
    payload = dict(rows[0]["payload"])
    assert payload["stage"] == "NO_SETUP"
    assert payload["reason"] == "structure_fail"
    assert payload["sample_domain"] == SAMPLE_DOMAIN
    assert payload["natural_setup_only"] is True
    assert payload["forced_entry_enabled"] is False
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["phase18_evidence"] is False


def test_observation_identity_changes_with_closed_trigger_bar() -> None:
    first = prototype_strategy_observation_event_id(
        paper_epoch_id="aether-prototype-new-system-test-001",
        asset_id="btc",
        trigger_close_utc=T0,
        reason="structure_fail",
    )
    later = prototype_strategy_observation_event_id(
        paper_epoch_id="aether-prototype-new-system-test-001",
        asset_id="btc",
        trigger_close_utc=T0 + timedelta(hours=1),
        reason="structure_fail",
    )
    assert first != later
