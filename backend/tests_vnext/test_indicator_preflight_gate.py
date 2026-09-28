from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    preflight_canonical_forward_paper_campaign_from_book,
    preflight_forward_paper_campaign_from_book,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 7, 0, tzinfo=UTC)


def _empty_book() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_canonical_preflight_accepts_bound_indicator_conventions() -> None:
    engine, store = _empty_book()
    with engine.begin() as conn:
        result = preflight_canonical_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="indicator-authority-test",
            as_of_utc=T0,
        )

    # The empty book still fails for unrelated canonical prerequisites, but
    # Indicator Convention v1 must no longer contribute any blocker.
    assert result.startable is False
    assert result.baseline_snapshot_hash is None
    assert "canonical_policy_snapshot_missing" in result.blockers
    assert "ema_calculation_convention_unbound" not in result.blockers
    assert "atr_calculation_convention_unbound" not in result.blockers
    assert "realized_vol_calculation_convention_unbound" not in result.blockers


def test_generic_diagnostic_preflight_does_not_force_canonical_indicator_gate() -> None:
    engine, store = _empty_book()
    with engine.begin() as conn:
        result = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="diagnostic-preflight",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
            as_of_utc=T0,
        )

    assert "ema_calculation_convention_unbound" not in result.blockers
    assert "atr_calculation_convention_unbound" not in result.blockers
    assert "realized_vol_calculation_convention_unbound" not in result.blockers
