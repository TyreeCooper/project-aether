from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from aether_vnext.execution_provider import execution_provider_profile
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.registry_runtime import RuntimeRegistryBinding
from aether_vnext.tape_binding import TapeSourceBinding, bind_tape_sources
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy


UTC = timezone.utc


def _runtime_mes() -> RuntimeRegistryBinding:
    return RuntimeRegistryBinding(
        asset_id="mes",
        broker_symbol="MESZ26",
        primary_market_source_id="ninjatrader_market_data",
        fallback_market_source_id=None,
        stale_threshold_ms=1000,
        calendar_provider_id="cme_calendar",
        current_contract="MESZ26",
        market_data_contract_id=123,
        expiry_utc=datetime(2026, 12, 18, tzinfo=UTC),
        next_contract="MESH27",
    )


def test_mes_execution_economics_remain_ninjatrader_owned() -> None:
    mes = SEED_REGISTRY["mes"]
    execution = execution_provider_profile(mes, runtime_binding=_runtime_mes())
    assert execution.broker == "NinjaTrader"
    assert execution.executable_symbol == "MESZ26"
    assert execution.fee_schedule_id == mes.fee_schedule_id
    assert execution.margin_model == mes.margin_model
    assert execution.maximum_quantity == mes.maximum_quantity
    assert execution.tape_source_ids == ()


def test_tape_source_changes_do_not_change_execution_profile() -> None:
    mes = SEED_REGISTRY["mes"]
    policy = TapeQuorumPolicy(
        asset_class=TapeAssetClass.FUTURES,
        max_source_age_ms=1000,
        max_divergence_bps=5.0,
    )
    first = bind_tape_sources(
        mes,
        tuple(
            TapeSourceBinding(source, "CME", "MESZ26", "MESZ26")
            for source in ("a", "b", "c")
        ),
        policy=policy,
    )
    second = replace(
        first,
        sources=tuple(
            TapeSourceBinding(source, "CME", "MESZ26", "MESZ26")
            for source in ("x", "y", "z")
        ),
    )
    assert first.sources != second.sources
    assert (
        execution_provider_profile(mes, runtime_binding=_runtime_mes())
        == execution_provider_profile(mes, runtime_binding=_runtime_mes())
    )


def test_execution_profile_rejects_cross_asset_runtime_binding() -> None:
    mes = SEED_REGISTRY["mes"]
    wrong = replace(_runtime_mes(), asset_id="mnq")
    try:
        execution_provider_profile(mes, runtime_binding=wrong)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("cross-asset runtime binding must fail")
