from __future__ import annotations

from aether_vnext.indicator_authority import (
    INDICATOR_AUTHORITIES,
    indicator_authority,
    indicator_authority_blockers,
)


def test_named_runtime_indicator_conventions_are_explicit() -> None:
    assert set(INDICATOR_AUTHORITIES) == {
        "ema",
        "atr",
        "realized_vol",
        "prior_closed_bar_range",
    }

    assert indicator_authority("ema").source_bound is False
    assert indicator_authority("atr").source_bound is False
    assert indicator_authority("realized_vol").source_bound is False
    assert indicator_authority("prior_closed_bar_range").source_bound is True


def test_unbound_indicator_conventions_fail_closed() -> None:
    assert indicator_authority_blockers(
        ("ema", "atr", "realized_vol")
    ) == (
        "ema_calculation_convention_unbound",
        "atr_calculation_convention_unbound",
        "realized_vol_calculation_convention_unbound",
    )


def test_source_bound_prior_range_adds_no_blocker() -> None:
    assert indicator_authority_blockers(
        ("prior_closed_bar_range",)
    ) == ()


def test_duplicate_requirements_do_not_duplicate_blockers() -> None:
    assert indicator_authority_blockers(
        ("ema", "ema", "prior_closed_bar_range")
    ) == ("ema_calculation_convention_unbound",)


def test_unknown_indicator_is_explicitly_blocked() -> None:
    assert indicator_authority_blockers(
        ("future_indicator",)
    ) == ("indicator_authority_unknown:future_indicator",)
