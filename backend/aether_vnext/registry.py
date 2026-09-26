"""Canonical AETHER vNext Product Registry.

The registry encodes only source-supported product truth. Unknown broker/live-data
bindings remain explicit UNKNOWN/UNBOUND values rather than being invented.

Later adapter layers may bind exact executable contract symbols or market-data
providers, but they may not mutate the economic identity of a frozen registry row.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from aether_vnext.freeze import PRODUCT_SPECS
from aether_vnext.seed_truth import ASSET_CALENDAR, ASSET_FEE_SCHEDULE, SEED_PRODUCT_MATH


class ProductType(StrEnum):
    SPOT_CRYPTO = "spot_crypto"
    FX = "fx"
    MICRO_FUTURE = "micro_future"
    TREASURY_FUTURE = "treasury_future"
    EQUITY = "equity"


class ShortabilityState(StrEnum):
    NOT_SUPPORTED = "not_supported"
    AVAILABLE = "available"
    LOCATE_REQUIRED = "locate_required"
    UNKNOWN = "unknown"


class LifecycleState(StrEnum):
    ACTIVE = "active"
    ROLL_BLOCKED = "roll_blocked"
    HALTED = "halted"
    EXPIRED = "expired"
    RETIRED = "retired"


class BindingState(StrEnum):
    BOUND = "bound"
    UNBOUND = "unbound"
    NOT_APPLICABLE = "not_applicable"


class LiveAdapterStatus(StrEnum):
    NOT_AUTHORIZED = "not_authorized"


@dataclass(frozen=True, slots=True)
class FuturesLifecycle:
    continuous_research_symbol: str
    current_contract: str | None
    expiry_utc: datetime | None
    roll_cutoff_hours_before_expiry: int
    next_contract: str | None
    roll_to: str | None
    research_only_continuous: bool = True
    automatic_roll_allowed: bool = False

    @property
    def roll_cutoff_utc(self) -> datetime | None:
        if self.expiry_utc is None:
            return None
        return self.expiry_utc - timedelta(hours=self.roll_cutoff_hours_before_expiry)

    def fire_eligible(self, as_of_utc: datetime) -> bool:
        if self.current_contract is None or self.expiry_utc is None:
            return False
        cutoff = self.roll_cutoff_utc
        return cutoff is not None and as_of_utc < cutoff


@dataclass(frozen=True, slots=True)
class ProductRegistryRow:
    asset_id: str
    canonical_symbol: str
    broker_symbol: str | None
    venue: str
    broker: str
    product_type: ProductType
    base_currency: str | None
    quote_currency: str | None
    settlement_currency: str

    long_supported: bool
    short_supported: bool
    borrow_required: bool
    shortability_state: ShortabilityState

    unit: str
    quantity_step: float
    minimum_quantity: float
    maximum_quantity: float | None
    minimum_notional: float | None

    tick_size: float | None
    pip_size: float | None
    point_value: float | None
    quote_precision: int | None
    price_precision: int | None

    margin_model: str
    initial_margin: float | None
    maintenance_margin: float | None
    cash_settlement_behavior: str

    fee_schedule_id: str
    spread_model_id: str
    slippage_model_id: str
    exchange_regulatory_fee_model_id: str | None

    calendar_id: str
    timezone: str
    maintenance_rule_id: str
    early_close_rule_id: str

    lifecycle_state: LifecycleState
    active_from: datetime | None
    active_to: datetime | None
    symbol_change: str | None
    corporate_action_flags: tuple[str, ...]
    expiry_utc: datetime | None
    roll_to: str | None
    retirement_reason: str | None
    futures_lifecycle: FuturesLifecycle | None

    order_types_supported: tuple[str, ...]
    paper_adapter_id: str
    live_adapter_status: LiveAdapterStatus
    venue_constraints: tuple[str, ...]

    primary_market_source_id: str | None
    fallback_market_source_id: str | None
    market_data_binding_state: BindingState
    stale_threshold_ms: int | None

    def product_side_supported(self, side: str, *, locate_ok: bool = False) -> bool:
        normalized = str(side).strip().lower()
        if normalized == "long":
            return self.long_supported
        if normalized != "short" or not self.short_supported:
            return False
        if self.borrow_required:
            return (
                self.shortability_state is ShortabilityState.AVAILABLE
                and bool(locate_ok)
            )
        return True

    def market_data_ready(self) -> bool:
        return (
            self.market_data_binding_state is BindingState.BOUND
            and self.primary_market_source_id is not None
            and self.stale_threshold_ms is not None
        )

    def lifecycle_fire_eligible(self, as_of_utc: datetime) -> bool:
        if self.lifecycle_state is not LifecycleState.ACTIVE:
            return False
        if self.active_from is not None and as_of_utc < self.active_from:
            return False
        if self.active_to is not None and as_of_utc >= self.active_to:
            return False
        if self.futures_lifecycle is not None:
            return self.futures_lifecycle.fire_eligible(as_of_utc)
        return True

    def executable_fire_eligible(
        self,
        *,
        as_of_utc: datetime,
        side: str,
        locate_ok: bool = False,
    ) -> bool:
        return (
            self.product_side_supported(side, locate_ok=locate_ok)
            and self.market_data_ready()
            and self.lifecycle_fire_eligible(as_of_utc)
        )


# Explicit paper adapter contracts. These IDs belong to vNext; they do not import
# or delegate to legacy app.* implementations.
PAPER_ADAPTER_BY_BROKER: Final = MappingProxyType(
    {
        "Kraken": "vnext.paper.kraken_spot",
        "tastyfx": "vnext.paper.tastyfx_fx",
        "NinjaTrader": "vnext.paper.ninja_futures",
        "IBKR": "vnext.paper.ibkr_equity",
    }
)


def _product_type(asset_id: str) -> ProductType:
    if asset_id in {"btc", "eth"}:
        return ProductType.SPOT_CRYPTO
    if asset_id in {"eurusd", "usdjpy"}:
        return ProductType.FX
    if asset_id == "us10y":
        return ProductType.TREASURY_FUTURE
    if asset_id in {"mes", "mnq", "mgc", "mcl"}:
        return ProductType.MICRO_FUTURE
    return ProductType.EQUITY


def _currencies(asset_id: str) -> tuple[str | None, str | None, str]:
    if asset_id == "btc":
        return "BTC", "USD", "USD"
    if asset_id == "eth":
        return "ETH", "USD", "USD"
    if asset_id == "eurusd":
        return "EUR", "USD", "USD"
    if asset_id == "usdjpy":
        return "USD", "JPY", "USD"
    return None, "USD", "USD"


def _canonical_symbol(asset_id: str) -> str:
    return {
        "btc": "BTC/USD",
        "eth": "ETH/USD",
        "eurusd": "EUR/USD",
        "usdjpy": "USD/JPY",
        "mes": "MES",
        "mnq": "MNQ",
        "mgc": "MGC",
        "mcl": "MCL",
        "us10y": "ZN",
        "nvda": "NVDA",
        "tsla": "TSLA",
        "pltr": "PLTR",
    }[asset_id]


def _broker_and_venue(asset_id: str) -> tuple[str, str]:
    if asset_id in {"btc", "eth"}:
        return "Kraken", "Kraken"
    if asset_id in {"eurusd", "usdjpy"}:
        return "tastyfx", "tastyfx"
    if asset_id in {"mes", "mnq", "mgc", "mcl", "us10y"}:
        return "NinjaTrader", "NinjaTrader"
    return "IBKR", "IBKR"


def _shortability(asset_id: str) -> tuple[bool, ShortabilityState]:
    frozen = PRODUCT_SPECS[asset_id]
    if not frozen.short_supported:
        return False, ShortabilityState.NOT_SUPPORTED
    if frozen.short_requires_locate:
        return True, ShortabilityState.LOCATE_REQUIRED
    return False, ShortabilityState.AVAILABLE


def _futures_lifecycle(asset_id: str) -> FuturesLifecycle | None:
    if asset_id not in {"mes", "mnq", "mgc", "mcl", "us10y"}:
        return None
    research_symbol = {
        "mes": "MES_CONTINUOUS",
        "mnq": "MNQ_CONTINUOUS",
        "mgc": "MGC_CONTINUOUS",
        "mcl": "MCL_CONTINUOUS",
        "us10y": "ZN_CONTINUOUS",
    }[asset_id]
    return FuturesLifecycle(
        continuous_research_symbol=research_symbol,
        current_contract=None,
        expiry_utc=None,
        roll_cutoff_hours_before_expiry=48,
        next_contract=None,
        roll_to=None,
    )


def _seed_row(asset_id: str) -> ProductRegistryRow:
    math = SEED_PRODUCT_MATH[asset_id]
    frozen = PRODUCT_SPECS[asset_id]
    broker, venue = _broker_and_venue(asset_id)
    borrow_required, shortability = _shortability(asset_id)
    base, quote, settlement = _currencies(asset_id)
    is_equity = asset_id in {"nvda", "tsla", "pltr"}

    # Only Kraken public market data is already concretely identified in the repo.
    # Every other provider binding remains UNBOUND instead of guessed.
    if asset_id in {"btc", "eth"}:
        primary_source = "kraken_public"
        binding_state = BindingState.BOUND
        # The frozen specification requires a stale threshold but does not bind a
        # numeric seed. Keep it None until the Policy Book supplies it.
        stale_threshold = None
    else:
        primary_source = None
        binding_state = BindingState.UNBOUND
        stale_threshold = None

    futures = _futures_lifecycle(asset_id)

    return ProductRegistryRow(
        asset_id=asset_id,
        canonical_symbol=_canonical_symbol(asset_id),
        broker_symbol=(
            "XBTUSD" if asset_id == "btc"
            else "ETHUSD" if asset_id == "eth"
            else None
        ),
        venue=venue,
        broker=broker,
        product_type=_product_type(asset_id),
        base_currency=base,
        quote_currency=quote,
        settlement_currency=settlement,
        long_supported=frozen.long_supported,
        short_supported=frozen.short_supported,
        borrow_required=borrow_required,
        shortability_state=shortability,
        unit=math.unit,
        quantity_step=math.quantity_step,
        minimum_quantity=math.quantity_step,
        maximum_quantity=(
            float(math.max_contracts) if math.max_contracts is not None else None
        ),
        minimum_notional=None,
        tick_size=math.tick_size,
        pip_size=math.pip_size,
        point_value=(
            None
            if math.tick_size is None or math.tick_value_usd is None
            else math.tick_value_usd / math.tick_size
        ),
        quote_precision=None,
        price_precision=None,
        margin_model=math.margin_model,
        initial_margin=math.paper_margin_value,
        maintenance_margin=None,
        cash_settlement_behavior=(
            "cash_inventory" if asset_id in {"btc", "eth"}
            else "variation_margin" if futures is not None
            else "settlement_aware" if is_equity
            else "otc_margin"
        ),
        fee_schedule_id=ASSET_FEE_SCHEDULE[asset_id],
        spread_model_id="top_of_book_spread_v1",
        slippage_model_id="adverse_5bps_v1",
        exchange_regulatory_fee_model_id=(
            "ibkr_equity_regulatory_v1" if is_equity else None
        ),
        calendar_id=ASSET_CALENDAR[asset_id],
        timezone="America/New_York",
        maintenance_rule_id=f"{ASSET_CALENDAR[asset_id]}:maintenance",
        early_close_rule_id=f"{ASSET_CALENDAR[asset_id]}:early_close",
        lifecycle_state=LifecycleState.ACTIVE,
        active_from=None,
        active_to=None,
        symbol_change=None,
        corporate_action_flags=(),
        expiry_utc=None,
        roll_to=None,
        retirement_reason=None,
        futures_lifecycle=futures,
        order_types_supported=("market",),
        paper_adapter_id=PAPER_ADAPTER_BY_BROKER[broker],
        live_adapter_status=LiveAdapterStatus.NOT_AUTHORIZED,
        venue_constraints=("paper_only", "live_hard_blocked"),
        primary_market_source_id=primary_source,
        fallback_market_source_id=None,
        market_data_binding_state=binding_state,
        stale_threshold_ms=stale_threshold,
    )


SEED_REGISTRY: Final = MappingProxyType(
    {asset_id: _seed_row(asset_id) for asset_id in SEED_PRODUCT_MATH}
)


def registry_row(asset_id: str) -> ProductRegistryRow:
    return SEED_REGISTRY[str(asset_id).strip().lower()]


def bind_market_data(
    row: ProductRegistryRow,
    *,
    primary_source_id: str,
    stale_threshold_ms: int,
    fallback_source_id: str | None = None,
) -> ProductRegistryRow:
    if stale_threshold_ms <= 0:
        raise ValueError("stale_threshold_ms must be positive")
    if not str(primary_source_id).strip():
        raise ValueError("primary_source_id is required")
    return replace(
        row,
        primary_market_source_id=str(primary_source_id),
        fallback_market_source_id=fallback_source_id,
        market_data_binding_state=BindingState.BOUND,
        stale_threshold_ms=int(stale_threshold_ms),
    )


def bind_futures_contract(
    row: ProductRegistryRow,
    *,
    current_contract: str,
    expiry_utc: datetime,
    next_contract: str | None,
) -> ProductRegistryRow:
    if row.futures_lifecycle is None:
        raise ValueError("product is not a futures contract family")
    if not str(current_contract).strip():
        raise ValueError("current_contract is required")
    if expiry_utc.tzinfo is None:
        raise ValueError("expiry_utc must be timezone-aware")
    lifecycle = replace(
        row.futures_lifecycle,
        current_contract=str(current_contract),
        expiry_utc=expiry_utc,
        next_contract=next_contract,
        roll_to=next_contract,
    )
    return replace(
        row,
        broker_symbol=str(current_contract),
        expiry_utc=expiry_utc,
        roll_to=next_contract,
        futures_lifecycle=lifecycle,
    )


def validate_registry_row(row: ProductRegistryRow) -> tuple[str, ...]:
    errors: list[str] = []
    if not row.asset_id:
        errors.append("missing_asset_id")
    if not row.canonical_symbol:
        errors.append("missing_canonical_symbol")
    if row.quantity_step <= 0:
        errors.append("invalid_quantity_step")
    if row.minimum_quantity <= 0:
        errors.append("invalid_minimum_quantity")
    if not row.fee_schedule_id:
        errors.append("missing_fee_schedule")
    if not row.calendar_id:
        errors.append("missing_calendar")
    if not row.paper_adapter_id:
        errors.append("missing_paper_adapter")
    if row.short_supported is False and row.shortability_state is not ShortabilityState.NOT_SUPPORTED:
        errors.append("shortability_conflict")
    if row.futures_lifecycle is not None:
        if row.futures_lifecycle.roll_cutoff_hours_before_expiry != 48:
            errors.append("invalid_roll_cutoff")
        if row.futures_lifecycle.automatic_roll_allowed:
            errors.append("automatic_roll_forbidden")
    return tuple(errors)
