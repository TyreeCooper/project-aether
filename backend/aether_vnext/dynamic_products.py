"""Source-backed dynamic product projection for broad provider universes.

This module does not invent product economics. Dynamic products are materialized only
from provider facts already carried by discovery plus existing Firm/provider policy
inputs supplied by the caller. Missing facts remain explicit requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping

from aether_vnext.registry import (
    BindingState,
    LifecycleState,
    LiveAdapterStatus,
    ProductRegistryRow,
    ProductType,
    ShortabilityState,
)


_SEED_KRAKEN_SYMBOLS = {
    "BTC/USD": "btc",
    "XBT/USD": "btc",
    "ETH/USD": "eth",
}


@dataclass(frozen=True, slots=True)
class DynamicProductProjection:
    asset_id: str
    product: ProductRegistryRow | None
    requirements: tuple[str, ...]
    source_backed: bool

    @property
    def paper_execution_ready(self) -> bool:
        return self.product is not None and not self.requirements


def canonical_provider_asset_id(
    *,
    provider: str,
    symbol: str,
    execution_symbol: str | None,
) -> str:
    provider_name = str(provider).strip()
    display_symbol = str(symbol).strip().upper()
    if provider_name == "Kraken" and display_symbol in _SEED_KRAKEN_SYMBOLS:
        return _SEED_KRAKEN_SYMBOLS[display_symbol]

    execution = str(execution_symbol or "").strip()
    identity = execution or display_symbol
    slug = re.sub(r"[^a-z0-9]+", "-", identity.lower()).strip("-")
    if not provider_name or not slug:
        raise ValueError("provider and stable provider symbol are required")
    provider_slug = re.sub(r"[^a-z0-9]+", "-", provider_name.lower()).strip("-")
    return f"{provider_slug}:{slug}"


def project_kraken_spot_product(
    focus_row: Mapping[str, object],
    *,
    primary_market_source_id: str | None,
    stale_threshold_ms: int | None,
) -> DynamicProductProjection:
    """Build a PAPER Kraken spot product strictly from provider + Firm facts."""
    provider = str(focus_row.get("provider") or "").strip()
    symbol = str(focus_row.get("symbol") or "").strip().upper()
    execution_symbol = str(focus_row.get("execution_symbol") or "").strip() or None
    asset_id = canonical_provider_asset_id(
        provider=provider,
        symbol=symbol,
        execution_symbol=execution_symbol,
    )

    requirements: list[str] = []
    if provider != "Kraken":
        requirements.append("kraken_provider_required")
    if str(focus_row.get("asset_class") or "") != "spot_crypto":
        requirements.append("spot_crypto_required")

    base = str(focus_row.get("base_currency") or "").strip().upper() or None
    quote = str(focus_row.get("quote_currency") or "").strip().upper() or None
    if base is None:
        requirements.append("base_currency_missing")
    if quote is None:
        requirements.append("quote_currency_missing")
    elif quote != "USD":
        # The prototype book is USD-denominated. No FX conversion is guessed.
        requirements.append("usd_settlement_route_required")

    def positive(name: str) -> float | None:
        raw = focus_row.get(name)
        if raw is None:
            requirements.append(f"{name}_missing")
            return None
        value = float(raw)
        if value <= 0:
            requirements.append(f"{name}_invalid")
            return None
        return value

    quantity_step = positive("quantity_step")
    minimum_quantity = positive("minimum_quantity")
    tick_size = positive("tick_size")
    minimum_notional_raw = focus_row.get("minimum_notional")
    minimum_notional = None
    if minimum_notional_raw is not None:
        minimum_notional = float(minimum_notional_raw)
        if minimum_notional <= 0:
            requirements.append("minimum_notional_invalid")
            minimum_notional = None

    if execution_symbol is None:
        requirements.append("execution_symbol_missing")
    source_id = str(primary_market_source_id or "").strip() or None
    if source_id is None:
        requirements.append("market_data_source_missing")
    if stale_threshold_ms is None:
        requirements.append("stale_threshold_missing")
    elif int(stale_threshold_ms) <= 0:
        requirements.append("stale_threshold_invalid")

    requirements = list(dict.fromkeys(requirements))
    if requirements:
        return DynamicProductProjection(
            asset_id=asset_id,
            product=None,
            requirements=tuple(requirements),
            source_backed=True,
        )

    assert base is not None
    assert quote == "USD"
    assert execution_symbol is not None
    assert quantity_step is not None
    assert minimum_quantity is not None
    assert tick_size is not None
    assert source_id is not None
    assert stale_threshold_ms is not None

    row = ProductRegistryRow(
        asset_id=asset_id,
        canonical_symbol=symbol,
        broker_symbol=execution_symbol,
        venue="Kraken",
        broker="Kraken",
        product_type=ProductType.SPOT_CRYPTO,
        base_currency=base,
        quote_currency=quote,
        settlement_currency="USD",
        long_supported=True,
        short_supported=False,
        borrow_required=False,
        shortability_state=ShortabilityState.NOT_SUPPORTED,
        unit=base,
        quantity_step=quantity_step,
        minimum_quantity=minimum_quantity,
        maximum_quantity=None,
        minimum_notional=minimum_notional,
        tick_size=tick_size,
        pip_size=None,
        point_value=None,
        quote_precision=None,
        price_precision=None,
        margin_model="cash_100pct",
        initial_margin=1.0,
        maintenance_margin=None,
        cash_settlement_behavior="cash_inventory",
        fee_schedule_id="kraken_spot_taker_v1",
        spread_model_id="top_of_book_spread_v1",
        slippage_model_id="adverse_5bps_v1",
        exchange_regulatory_fee_model_id=None,
        calendar_id="crypto_24x7",
        timezone="America/New_York",
        maintenance_rule_id="crypto_24x7:maintenance",
        early_close_rule_id="crypto_24x7:early_close",
        lifecycle_state=LifecycleState.ACTIVE,
        active_from=None,
        active_to=None,
        symbol_change=None,
        corporate_action_flags=(),
        expiry_utc=None,
        roll_to=None,
        retirement_reason=None,
        futures_lifecycle=None,
        order_types_supported=("market",),
        paper_adapter_id="vnext.paper.kraken_spot",
        live_adapter_status=LiveAdapterStatus.NOT_AUTHORIZED,
        venue_constraints=("paper_only", "live_hard_blocked"),
        primary_market_source_id=source_id,
        fallback_market_source_id=None,
        market_data_binding_state=BindingState.BOUND,
        stale_threshold_ms=int(stale_threshold_ms),
    )
    return DynamicProductProjection(
        asset_id=asset_id,
        product=row,
        requirements=(),
        source_backed=True,
    )
