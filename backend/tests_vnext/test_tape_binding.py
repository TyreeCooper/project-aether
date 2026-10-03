from __future__ import annotations

from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.tape_binding import (
    TapeSourceBinding,
    bind_tape_sources,
    tape_binding_blockers,
)
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy


def _policy() -> TapeQuorumPolicy:
    return TapeQuorumPolicy(
        asset_class=TapeAssetClass.FUTURES,
        max_source_age_ms=1000,
        max_divergence_bps=5.0,
    )


def test_tape_binding_has_no_execution_provider_ownership() -> None:
    mes = SEED_REGISTRY["mes"]
    binding = bind_tape_sources(
        mes,
        (
            TapeSourceBinding("feed-a", "CME", "MESZ26", "MESZ26"),
            TapeSourceBinding("feed-b", "CME", "MESZ26", "MESZ26"),
            TapeSourceBinding("feed-c", "CME", "MESZ26", "MESZ26"),
        ),
        policy=_policy(),
    )
    assert binding.asset_id == "mes"
    assert binding.execution_provider is None
    assert mes.broker == "NinjaTrader"
    assert tape_binding_blockers(binding) == ()


def test_ninjatrader_execution_identity_does_not_control_tape_sources() -> None:
    mes = SEED_REGISTRY["mes"]
    binding = bind_tape_sources(
        mes,
        (
            TapeSourceBinding("institutional-a", "CME", "MESZ26", "MESZ26"),
            TapeSourceBinding("institutional-b", "CME", "MESZ26", "MESZ26"),
            TapeSourceBinding("institutional-c", "CME", "MESZ26", "MESZ26"),
        ),
        policy=_policy(),
    )
    assert all("ninja" not in row.source_id for row in binding.sources)
    assert mes.fee_schedule_id.startswith("ninja")
    assert tape_binding_blockers(binding) == ()


def test_tape_binding_requires_three_enabled_sources_for_full_quorum() -> None:
    mes = SEED_REGISTRY["mes"]
    binding = bind_tape_sources(
        mes,
        (
            TapeSourceBinding("feed-a", "CME", "MESZ26", "MESZ26"),
            TapeSourceBinding("feed-b", "CME", "MESZ26", "MESZ26"),
        ),
        policy=_policy(),
    )
    assert tape_binding_blockers(binding) == (
        "tape_source_quorum_binding_incomplete",
    )
