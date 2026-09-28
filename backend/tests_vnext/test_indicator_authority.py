from __future__ import annotations

from aether_vnext.indicator_authority import (
    INDICATOR_AUTHORITIES,
    indicator_authority,
    indicator_authority_blockers,
)


def test_named_runtime_indicator_conventions_are_explicit_and_bound() -> None:
    assert set(INDICATOR_AUTHORITIES) == {
        "ema",
        "atr",
        "realized_vol",
        "prior_closed_bar_range",
    }

    assert indicator_authority("ema").source_bound is True
    assert indicator_authority("atr").source_bound is True
    assert indicator_authority("realized_vol").source_bound is True
    assert indicator_authority("prior_closed_bar_range").source_bound is True


def test_indicator_convention_v1_clears_named_math_blockers() -> None:
    assert indicator_authority_blockers(
        ("ema", "atr", "realized_vol", "prior_closed_bar_range")
    ) == ()


def test_duplicate_bound_requirements_remain_clear() -> None:
    assert indicator_authority_blockers(
        ("ema", "ema", "prior_closed_bar_range")
    ) == ()


def test_unknown_indicator_is_explicitly_blocked() -> None:
    assert indicator_authority_blockers(
        ("future_indicator",)
    ) == ("indicator_authority_unknown:future_indicator",)
