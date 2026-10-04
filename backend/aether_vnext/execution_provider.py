"""Execution-provider identity and economics projection for AETHER vNext.

This is the execution side of the Tape/provider split. It projects existing frozen
Product Registry and reviewed runtime-binding facts; it does not derive any value
from Tape sources or composite prices.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.registry import ProductRegistryRow
from aether_vnext.registry_runtime import RuntimeRegistryBinding


@dataclass(frozen=True, slots=True)
class ExecutionProviderProfile:
    asset_id: str
    broker: str
    executable_symbol: str | None
    fee_schedule_id: str
    spread_model_id: str
    slippage_model_id: str
    exchange_regulatory_fee_model_id: str | None
    margin_model: str
    initial_margin: float | None
    maintenance_margin: float | None
    quantity_step: float
    minimum_quantity: float
    maximum_quantity: float | None
    tick_size: float | None
    pip_size: float | None
    point_value: float | None

    @property
    def tape_source_ids(self) -> tuple[()]:
        """Execution economics do not own or depend on Tape-source selection."""
        return ()


def execution_provider_profile(
    product: ProductRegistryRow,
    *,
    runtime_binding: RuntimeRegistryBinding | None = None,
) -> ExecutionProviderProfile:
    if runtime_binding is not None and (
        runtime_binding.asset_id.strip().lower() != product.asset_id
    ):
        raise ValueError("runtime binding asset does not match execution product")

    executable_symbol = product.broker_symbol
    if runtime_binding is not None:
        executable_symbol = (
            runtime_binding.current_contract
            or runtime_binding.broker_symbol
            or executable_symbol
        )

    return ExecutionProviderProfile(
        asset_id=product.asset_id,
        broker=product.broker,
        executable_symbol=executable_symbol,
        fee_schedule_id=product.fee_schedule_id,
        spread_model_id=product.spread_model_id,
        slippage_model_id=product.slippage_model_id,
        exchange_regulatory_fee_model_id=(
            product.exchange_regulatory_fee_model_id
        ),
        margin_model=product.margin_model,
        initial_margin=product.initial_margin,
        maintenance_margin=product.maintenance_margin,
        quantity_step=product.quantity_step,
        minimum_quantity=product.minimum_quantity,
        maximum_quantity=product.maximum_quantity,
        tick_size=product.tick_size,
        pip_size=product.pip_size,
        point_value=product.point_value,
    )
