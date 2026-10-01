from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.calendars import (
    CalendarException,
    CalendarExceptionKind,
)
from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.market_data import RawQuote
from aether_vnext.market_ingress import (
    assess_market_ingress_health,
    ingest_market_quotes,
)
from aether_vnext.store import VNextStore
from tests_vnext.runtime_registry_support import record_test_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 1, 35, tzinfo=UTC)


class StaticCalendarProvider:
    provider_id = "test.calendar"

    def exception_for(
        self,
        *,
        calendar_id: str,
        session_date: date,
    ) -> CalendarException:
        return CalendarException(
            calendar_id=calendar_id,
            session_date=session_date,
            kind=CalendarExceptionKind.NORMAL,
        )


class WrongCalendarProvider(StaticCalendarProvider):
    provider_id = "wrong.calendar"


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="market-ingress-policy",
                effective_at_utc=T0 - timedelta(days=1),
                changed_by="test",
                change_reason="market ingress",
                payload={},
                created_at_utc=T0 - timedelta(days=1),
            )
        )
    return engine, store


def _quote(
    asset_id: str,
    *,
    source_id: str,
    exchange_ts: datetime,
    venue: str,
) -> RawQuote:
    return RawQuote(
        asset_id=asset_id,
        venue=venue,
        source_id=source_id,
        bid=99.0,
        ask=101.0,
        last=100.0,
        mark=100.0,
        exchange_ts=exchange_ts,
        received_ts=exchange_ts,
        adapter_version="test-adapter-v1",
    )


def test_crypto_ingress_persists_observation_and_append_only_attempt() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        binding_hash = record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        result = ingest_market_quotes(
            conn,
            store,
            asset_id="btc",
            quotes=(
                _quote(
                    "btc",
                    source_id="test.market.btc",
                    exchange_ts=T0,
                    venue="Kraken",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(milliseconds=100),
        )
        attempt = store.latest_market_ingress_attempt(conn, asset_id="btc")

    assert result.executable is True
    assert result.reason == "market_valid"
    assert result.runtime_registry_binding_hash == binding_hash
    assert result.observation is not None
    assert attempt is not None
    assert attempt["observation_id"] == result.observation.observation_id
    assert attempt["executable"] is True


def test_stale_quote_records_failed_attempt_without_inventing_observation() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        result = ingest_market_quotes(
            conn,
            store,
            asset_id="btc",
            quotes=(
                _quote(
                    "btc",
                    source_id="test.market.btc",
                    exchange_ts=T0,
                    venue="Kraken",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(seconds=2),
        )
        attempt = store.latest_market_ingress_attempt(conn, asset_id="btc")
        observation_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["market_observations"]
            )
        ).scalar_one()

    assert result.executable is False
    assert result.reason == "quote_stale"
    assert result.observation is None
    assert attempt is not None
    assert attempt["observation_id"] is None
    assert observation_count == 0


def test_exchange_ingress_requires_bound_calendar_provider_identity() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="nvda",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        unavailable = ingest_market_quotes(
            conn,
            store,
            asset_id="nvda",
            quotes=(),
            calendar_provider=None,
            as_of_utc=T0,
        )

    assert unavailable.executable is False
    assert unavailable.reason == "calendar_provider_unavailable"

    engine2, store2 = _store()
    with engine2.begin() as conn:
        record_test_runtime_binding(
            conn,
            store2,
            asset_id="nvda",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        mismatch = ingest_market_quotes(
            conn,
            store2,
            asset_id="nvda",
            quotes=(),
            calendar_provider=WrongCalendarProvider(),
            as_of_utc=T0,
        )

    assert mismatch.executable is False
    assert mismatch.reason == "calendar_provider_identity_mismatch"


def test_fx_otc_ingress_needs_no_exchange_calendar_provider() -> None:
    engine, store = _store()
    # T0 is Saturday evening EDT. FX closure comes from the frozen OTC weekly
    # contract; no exchange-holiday provider is needed or consulted.
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="eurusd",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        result = ingest_market_quotes(
            conn,
            store,
            asset_id="eurusd",
            quotes=(
                _quote(
                    "eurusd",
                    source_id="test.market.eurusd",
                    exchange_ts=T0,
                    venue="tastyfx",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(milliseconds=100),
        )

    assert result.observation is not None
    assert result.executable is False
    assert result.reason == "session_closed"
    assert result.calendar_reason == "weekend"


def test_health_report_recomputes_freshness_from_persisted_exchange_time() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        ingest_market_quotes(
            conn,
            store,
            asset_id="btc",
            quotes=(
                _quote(
                    "btc",
                    source_id="test.market.btc",
                    exchange_ts=T0,
                    venue="Kraken",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(milliseconds=100),
        )
        fresh = assess_market_ingress_health(
            conn,
            store,
            asset_id="btc",
            as_of_utc=T0 + timedelta(milliseconds=500),
        )
        stale = assess_market_ingress_health(
            conn,
            store,
            asset_id="btc",
            as_of_utc=T0 + timedelta(seconds=2),
        )

    assert fresh.binding_ready is True
    assert fresh.fresh_now is True
    assert fresh.observation_age_now_ms == 500
    assert stale.fresh_now is False
    assert "latest_observation_stale_now" in stale.blockers


def test_health_report_is_explicit_when_ingress_never_ran() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        health = assess_market_ingress_health(
            conn,
            store,
            asset_id="btc",
            as_of_utc=T0,
        )

    assert health.binding_ready is True
    assert health.latest_attempt_id is None
    assert health.latest_reason == "market_ingress_not_observed"
    assert health.fresh_now is False



def test_dynamic_kraken_product_uses_same_canonical_market_ingress_gate() -> None:
    engine, store = _store()
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.02,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="test.market.dynamic.sol",
        stale_threshold_ms=1500,
    )
    assert projection.product is not None

    with engine.begin() as conn:
        product_hash = store.upsert_dynamic_product_state(
            conn,
            projection.product,
            source_ref="kraken:AssetPairs:SOLUSD",
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        result = ingest_market_quotes(
            conn,
            store,
            asset_id=projection.asset_id,
            quotes=(
                _quote(
                    projection.asset_id,
                    source_id="test.market.dynamic.sol",
                    exchange_ts=T0,
                    venue="Kraken",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(milliseconds=100),
        )
        health = assess_market_ingress_health(
            conn,
            store,
            asset_id=projection.asset_id,
            as_of_utc=T0 + timedelta(milliseconds=500),
        )

    assert result.executable is True
    assert result.reason == "market_valid"
    assert result.runtime_registry_binding_hash == product_hash
    assert result.observation is not None
    assert health.binding_present is True
    assert health.binding_ready is True
    assert health.fresh_now is True
    assert health.observation_age_now_ms == 500


def test_dynamic_product_still_rejects_stale_market_truth() -> None:
    engine, store = _store()
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.02,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="test.market.dynamic.sol",
        stale_threshold_ms=1500,
    )
    assert projection.product is not None

    with engine.begin() as conn:
        store.upsert_dynamic_product_state(
            conn,
            projection.product,
            source_ref="kraken:AssetPairs:SOLUSD",
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        result = ingest_market_quotes(
            conn,
            store,
            asset_id=projection.asset_id,
            quotes=(
                _quote(
                    projection.asset_id,
                    source_id="test.market.dynamic.sol",
                    exchange_ts=T0,
                    venue="Kraken",
                ),
            ),
            calendar_provider=None,
            as_of_utc=T0 + timedelta(seconds=2),
        )

    assert result.executable is False
    assert result.reason == "quote_stale"
    assert result.observation is None
