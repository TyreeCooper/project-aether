from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.news import (
    EventAssetLink,
    EventMarketResponse,
    HistoricalAnalogRun,
    NewsSource,
    NormalizedEvent,
    RawNewsItem,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _source(*, active: bool = True) -> NewsSource:
    return NewsSource(
        source_id="fed",
        source_name="Federal Reserve",
        source_class="official_macro",
        primary_or_secondary="primary",
        authority_class="official",
        base_timezone="America/New_York",
        provider_adapter_id="fed-official-v1",
        active=active,
        terms_licensing_metadata_ref="terms/fed",
    )


def _raw(*, title: str = "Policy statement") -> RawNewsItem:
    return RawNewsItem(
        news_item_id="news-1",
        source_id="fed",
        provider_item_id="provider-1",
        canonical_url="https://example.test/fed/1",
        title=title,
        body_hash="body-hash-1",
        published_at_utc=T0,
        first_seen_at_utc=T0 + timedelta(seconds=2),
        received_at_utc=T0 + timedelta(seconds=3),
        revision_of_news_item_id=None,
        correction_or_retraction=False,
        language="en",
        ingest_status="accepted",
        dedupe_key="dedupe-1",
        raw_payload_ref="payload/news-1",
    )


def _event(*, confidence: float = 0.9) -> NormalizedEvent:
    return NormalizedEvent(
        event_id="event-1",
        event_cluster_id="cluster-1",
        event_type="fomc_rate_decision",
        source_news_item_ids=("news-1",),
        assets=("usd", "us10y"),
        clusters=("rates",),
        canonical_event_at_utc=T0,
        information_available_at_utc=T0 + timedelta(seconds=2),
        scheduled=True,
        expected=True,
        consensus=4.25,
        actual=4.25,
        surprise_magnitude=0.0,
        direction="flat",
        severity=0.8,
        novelty=0.2,
        confidence=confidence,
        market_scope="macro",
        macro=True,
        policy=True,
        normalizer_version="normalizer-v1",
    )


def _link(*, confidence: float = 0.95) -> EventAssetLink:
    return EventAssetLink(
        event_id="event-1",
        asset_id="us10y",
        relation_type="direct_macro",
        confidence=confidence,
        evidence_source_ids=("fed",),
        created_at_utc=T0 + timedelta(seconds=4),
        linker_version="linker-v1",
    )


def _response(*, return_1h: float = 0.002) -> EventMarketResponse:
    return EventMarketResponse(
        event_id="event-1",
        asset_id="us10y",
        pre_event_observation_id="obs-pre-1",
        return_1m=0.0002,
        return_5m=0.0005,
        return_15m=0.001,
        return_1h=return_1h,
        return_4h=0.003,
        return_1d=0.004,
        mfe=0.005,
        mae=-0.001,
        realized_vol_change=0.01,
        volume_change=0.05,
        spread_change=-0.01,
        liquidity_change=0.02,
        correlation_change=0.03,
        continuation_or_reversal="continuation",
        stabilization_time=1800.0,
        market_data_version="market-v1",
    )


def _analog(*, scores: tuple[float, ...] = (0.9, 0.8)) -> HistoricalAnalogRun:
    return HistoricalAnalogRun(
        analog_run_id="analog-1",
        query_event_or_state_id="event-1",
        feature_spec_version="features-v1",
        as_of_utc=T0 + timedelta(days=1),
        eligible_history_cutoff_utc=T0,
        matched_event_ids=("event-old-1", "event-old-2"),
        similarity_scores=scores,
        outcome_distribution={"median_return_1h": 0.001},
        created_at_utc=T0 + timedelta(days=1, seconds=1),
        research_only=True,
    )


def test_news_source_round_trip_and_row_version() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        assert store.upsert_news_source(conn, _source()) == 1
        assert store.upsert_news_source(conn, _source(active=False)) == 2

    with engine.begin() as conn:
        loaded = store.load_news_source(conn, source_id="fed")
        row_version = conn.execute(
            sa.select(store.tables["news_sources"].c.row_version)
        ).scalar_one()

    assert loaded == _source(active=False)
    assert row_version == 2


def test_raw_news_item_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    item = _raw()
    with engine.begin() as conn:
        store.upsert_news_source(conn, _source())
        store.record_raw_news_item(conn, item)
        store.record_raw_news_item(conn, item)

    with engine.begin() as conn:
        assert store.load_raw_news_item(conn, news_item_id="news-1") == item
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["raw_news_items"]
            )
        ).scalar_one()
    assert count == 1

    with pytest.raises(ValueError, match="conflicting immutable raw news item"):
        with engine.begin() as conn:
            store.record_raw_news_item(conn, _raw(title="Changed title"))


def test_raw_news_item_requires_registered_source() -> None:
    engine, store = _store()
    with pytest.raises(KeyError, match="unknown news source"):
        with engine.begin() as conn:
            store.record_raw_news_item(conn, _raw())


def test_normalized_event_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    event = _event()
    with engine.begin() as conn:
        store.record_normalized_event(conn, event)
        store.record_normalized_event(conn, event)

    with engine.begin() as conn:
        loaded = store.load_normalized_event(conn, event_id="event-1")
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["normalized_events"]
            )
        ).scalar_one()
    assert loaded == event
    assert count == 1

    with pytest.raises(
        ValueError,
        match="conflicting immutable normalized event",
    ):
        with engine.begin() as conn:
            store.record_normalized_event(conn, _event(confidence=0.8))


def test_event_asset_link_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    link = _link()
    with engine.begin() as conn:
        store.record_event_asset_link(conn, link)
        store.record_event_asset_link(conn, link)

    with engine.begin() as conn:
        assert store.list_event_asset_links(
            conn,
            event_id="event-1",
        ) == (link,)

    with pytest.raises(
        ValueError,
        match="conflicting immutable event asset link",
    ):
        with engine.begin() as conn:
            store.record_event_asset_link(conn, _link(confidence=0.75))


def test_event_market_response_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    response = _response()
    with engine.begin() as conn:
        store.record_event_market_response(conn, response)
        store.record_event_market_response(conn, response)

    with engine.begin() as conn:
        loaded = store.load_event_market_response(
            conn,
            event_id="event-1",
            asset_id="us10y",
            market_data_version="market-v1",
        )
    assert loaded == response

    with pytest.raises(
        ValueError,
        match="conflicting immutable event market response",
    ):
        with engine.begin() as conn:
            store.record_event_market_response(
                conn,
                _response(return_1h=0.01),
            )


def test_historical_analog_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    run = _analog()
    with engine.begin() as conn:
        store.record_historical_analog_run(conn, run)
        store.record_historical_analog_run(conn, run)

    with engine.begin() as conn:
        loaded = store.load_historical_analog_run(
            conn,
            analog_run_id="analog-1",
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["historical_analog_runs"]
            )
        ).scalar_one()
    assert loaded == run
    assert loaded is not None and loaded.research_only is True
    assert count == 1

    with pytest.raises(
        ValueError,
        match="conflicting immutable historical analog run",
    ):
        with engine.begin() as conn:
            store.record_historical_analog_run(
                conn,
                _analog(scores=(0.7, 0.6)),
            )
