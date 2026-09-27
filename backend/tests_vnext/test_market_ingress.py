from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.calendars import (
    CalendarException,
    CalendarExceptionKind,
)
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


def test_noncrypto_ingress_requires_bound_calendar_provider_identity() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="eurusd",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        unavailable = ingest_market_quotes(
            conn,
            store,
            asset_id="eurusd",
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
            asset_id="eurusd",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        mismatch = ingest_market_quotes(
            conn,
            store2,
            asset_id="eurusd",
            quotes=(),
            calendar_provider=WrongCalendarProvider(),
            as_of_utc=T0,
        )

    assert mismatch.executable is False
    assert mismatch.reason == "calendar_provider_identity_mismatch"


def test_noncrypto_ingress_accepts_identified_calendar_provider_but_session_stays_authoritative() -> None:
    engine, store = _store()
    # T0 is Saturday evening EDT, so FX is closed regardless of a NORMAL holiday
    # exception. The infrastructure persists the quote but cannot make it executable.
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
            calendar_provider=StaticCalendarProvider(),
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
