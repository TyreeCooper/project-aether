"""Binding Part III seed product, fee, and session closures.

This module records only values explicitly fixed by the Master/Pre-Code Freeze.
Adapter-specific symbols and unspecified stale thresholds are deliberately not
invented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class SeedProductMath:
    asset_id: str
    broker: str
    unit: str
    quantity_step: float
    tick_size: float | None
    tick_value_usd: float | None
    pip_size: float | None
    pip_value_rule: str | None
    margin_model: str
    paper_margin_value: float | None
    seed_horizons: tuple[str, ...]
    max_contracts: int | None = None
    short_requires_locate: bool = False
    executable_contract_family: str | None = None


SEED_PRODUCT_MATH: Final = MappingProxyType(
    {
        "btc": SeedProductMath(
            asset_id="btc",
            broker="Kraken",
            unit="BTC",
            quantity_step=0.0001,
            tick_size=None,
            tick_value_usd=None,
            pip_size=None,
            pip_value_rule=None,
            margin_model="cash_100pct",
            paper_margin_value=1.0,
            seed_horizons=("daily_swing",),
        ),
        "eth": SeedProductMath(
            asset_id="eth",
            broker="Kraken",
            unit="ETH",
            quantity_step=0.001,
            tick_size=None,
            tick_value_usd=None,
            pip_size=None,
            pip_value_rule=None,
            margin_model="cash_100pct",
            paper_margin_value=1.0,
            seed_horizons=("daily_swing",),
        ),
        "eurusd": SeedProductMath(
            asset_id="eurusd",
            broker="tastyfx",
            unit="lot",
            quantity_step=0.01,
            tick_size=None,
            tick_value_usd=None,
            pip_size=0.0001,
            pip_value_rule="0.01 lot = $0.10 per pip",
            margin_model="notional_fraction",
            paper_margin_value=0.05,
            seed_horizons=("scalp", "intraday", "swing"),
        ),
        "usdjpy": SeedProductMath(
            asset_id="usdjpy",
            broker="tastyfx",
            unit="lot",
            quantity_step=0.01,
            tick_size=None,
            tick_value_usd=None,
            pip_size=0.01,
            pip_value_rule="pip USD = (0.01 * 1000) / JPY mark for 0.01 lot",
            margin_model="notional_fraction",
            paper_margin_value=0.05,
            seed_horizons=("scalp", "intraday", "swing"),
        ),
        "mes": SeedProductMath(
            asset_id="mes",
            broker="NinjaTrader",
            unit="contract",
            quantity_step=1.0,
            tick_size=0.25,
            tick_value_usd=1.25,
            pip_size=None,
            pip_value_rule=None,
            margin_model="overnight_seed_usd",
            paper_margin_value=1200.0,
            seed_horizons=("scalp", "intraday", "swing"),
            max_contracts=1,
        ),
        "mnq": SeedProductMath(
            asset_id="mnq",
            broker="NinjaTrader",
            unit="contract",
            quantity_step=1.0,
            tick_size=0.25,
            tick_value_usd=0.50,
            pip_size=None,
            pip_value_rule=None,
            margin_model="overnight_seed_usd",
            paper_margin_value=1400.0,
            seed_horizons=("scalp", "intraday", "swing"),
            max_contracts=1,
        ),
        "mgc": SeedProductMath(
            asset_id="mgc",
            broker="NinjaTrader",
            unit="contract",
            quantity_step=1.0,
            tick_size=0.10,
            tick_value_usd=1.00,
            pip_size=None,
            pip_value_rule=None,
            margin_model="overnight_seed_usd",
            paper_margin_value=1000.0,
            seed_horizons=("intraday", "swing"),
            max_contracts=1,
        ),
        "mcl": SeedProductMath(
            asset_id="mcl",
            broker="NinjaTrader",
            unit="contract",
            quantity_step=1.0,
            tick_size=0.01,
            tick_value_usd=1.00,
            pip_size=None,
            pip_value_rule=None,
            margin_model="overnight_seed_usd",
            paper_margin_value=1000.0,
            seed_horizons=("intraday", "swing"),
            max_contracts=1,
        ),
        "us10y": SeedProductMath(
            asset_id="us10y",
            broker="NinjaTrader",
            unit="contract",
            quantity_step=1.0,
            tick_size=1 / 64,
            tick_value_usd=15.625,
            pip_size=None,
            pip_value_rule=None,
            margin_model="overnight_seed_usd",
            paper_margin_value=800.0,
            seed_horizons=("swing",),
            max_contracts=1,
            executable_contract_family="ZN",
        ),
        "nvda": SeedProductMath(
            asset_id="nvda",
            broker="IBKR",
            unit="share",
            quantity_step=1.0,
            tick_size=0.01,
            tick_value_usd=None,
            pip_size=None,
            pip_value_rule=None,
            margin_model="reg_t_fraction",
            paper_margin_value=0.50,
            seed_horizons=("scalp", "intraday", "swing"),
            short_requires_locate=True,
        ),
        "tsla": SeedProductMath(
            asset_id="tsla",
            broker="IBKR",
            unit="share",
            quantity_step=1.0,
            tick_size=0.01,
            tick_value_usd=None,
            pip_size=None,
            pip_value_rule=None,
            margin_model="reg_t_fraction",
            paper_margin_value=0.50,
            seed_horizons=("scalp", "intraday", "swing"),
            short_requires_locate=True,
        ),
        "pltr": SeedProductMath(
            asset_id="pltr",
            broker="IBKR",
            unit="share",
            quantity_step=1.0,
            tick_size=0.01,
            tick_value_usd=None,
            pip_size=None,
            pip_value_rule=None,
            margin_model="reg_t_fraction",
            paper_margin_value=0.50,
            seed_horizons=("scalp", "intraday", "swing"),
            short_requires_locate=True,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    fee_schedule_id: str
    paper_model: str


FEE_SCHEDULES: Final = MappingProxyType(
    {
        "kraken_spot_taker_v1": FeeSchedule(
            "kraken_spot_taker_v1",
            "26 bps notional + book spread + 5 bps extra slip",
        ),
        "tastyfx_allin_v1": FeeSchedule(
            "tastyfx_allin_v1",
            "book spread + 5 bps extra slip; zero commission does not mean zero friction",
        ),
        "ninja_micros_v1": FeeSchedule(
            "ninja_micros_v1",
            "$0.35 commission + $0.15 fees per side per contract + spread + 5 bps",
        ),
        "ibkr_equity_v1": FeeSchedule(
            "ibkr_equity_v1",
            "max($0.005/share,$1) + SEC sell 0.0008% + spread + 5 bps; "
            "short + 50 bps/year borrow if venue silent",
        ),
    }
)


ASSET_FEE_SCHEDULE: Final = MappingProxyType(
    {
        "btc": "kraken_spot_taker_v1",
        "eth": "kraken_spot_taker_v1",
        "eurusd": "tastyfx_allin_v1",
        "usdjpy": "tastyfx_allin_v1",
        "mes": "ninja_micros_v1",
        "mnq": "ninja_micros_v1",
        "mgc": "ninja_micros_v1",
        "mcl": "ninja_micros_v1",
        "us10y": "ninja_micros_v1",
        "nvda": "ibkr_equity_v1",
        "tsla": "ibkr_equity_v1",
        "pltr": "ibkr_equity_v1",
    }
)


@dataclass(frozen=True, slots=True)
class SessionCalendarSummary:
    calendar_id: str
    focus_et: str
    eligible: str
    closed_or_maintenance: str
    note: str = ""


SESSION_CALENDARS: Final = MappingProxyType(
    {
        "crypto_24x7": SessionCalendarSummary(
            "crypto_24x7", "always", "always", "adapter outage only"
        ),
        "fx_otc": SessionCalendarSummary(
            "fx_otc",
            "London 03:00-12:00; New York 08:00-17:00",
            "Sun 17:00-Fri 17:00",
            "weekend + 16:59-17:05 rollover",
        ),
        "us_rth": SessionCalendarSummary(
            "us_rth",
            "09:30-16:00",
            "09:30-16:00",
            "holidays; early close 13:00",
            "no FIRE after 15:45 unless playbook",
        ),
        "us_fut_idx": SessionCalendarSummary(
            "us_fut_idx",
            "09:30-16:00",
            "Sun 18:00-Fri 17:00",
            "17:00-18:00 ET daily",
        ),
        "us_fut_metal_nrg": SessionCalendarSummary(
            "us_fut_metal_nrg",
            "08:00-13:30",
            "Sun 18:00-Fri 17:00",
            "17:00-18:00 ET daily",
        ),
        "us_fut_rates": SessionCalendarSummary(
            "us_fut_rates",
            "08:20-15:00",
            "Sun 18:00-Fri 17:00",
            "17:00-18:00 ET daily",
        ),
    }
)


ASSET_CALENDAR: Final = MappingProxyType(
    {
        "btc": "crypto_24x7",
        "eth": "crypto_24x7",
        "eurusd": "fx_otc",
        "usdjpy": "fx_otc",
        "mes": "us_fut_idx",
        "mnq": "us_fut_idx",
        "mgc": "us_fut_metal_nrg",
        "mcl": "us_fut_metal_nrg",
        "us10y": "us_fut_rates",
        "nvda": "us_rth",
        "tsla": "us_rth",
        "pltr": "us_rth",
    }
)
