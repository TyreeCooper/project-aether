from app.horizons import (
    HORIZON_REGISTRY,
    HorizonState,
    TradingHorizon,
    applicable_horizons,
    horizon_spec,
)
from app.instruments import INSTRUMENTS


def test_registry_contains_all_declared_horizons():
    assert set(HORIZON_REGISTRY) == set(TradingHorizon)


def test_hft_is_explicitly_infrastructure_gated():
    spec = horizon_spec("hft")
    assert spec.state is HorizonState.INFRASTRUCTURE_GATED
    assert spec.execution_enabled is False


def test_practical_horizons_are_paper_candidates():
    for horizon in (
        TradingHorizon.SCALP,
        TradingHorizon.INTRADAY,
        TradingHorizon.SWING,
        TradingHorizon.POSITION,
    ):
        spec = horizon_spec(horizon)
        assert spec.state is HorizonState.CANDIDATE
        assert spec.execution_enabled is True
        assert spec.reason == "paper_candidate_only"


def test_all_twelve_books_share_the_same_applicable_horizon_surface():
    assert len(INSTRUMENTS) == 12
    expected = applicable_horizons()
    assert expected == (
        TradingHorizon.HFT,
        TradingHorizon.SCALP,
        TradingHorizon.INTRADAY,
        TradingHorizon.SWING,
        TradingHorizon.POSITION,
    )
    for asset_id in INSTRUMENTS:
        assert asset_id
        assert applicable_horizons() == expected


def test_execution_surface_excludes_gated_hft():
    assert applicable_horizons(include_gated=False) == (
        TradingHorizon.SCALP,
        TradingHorizon.INTRADAY,
        TradingHorizon.SWING,
        TradingHorizon.POSITION,
    )
