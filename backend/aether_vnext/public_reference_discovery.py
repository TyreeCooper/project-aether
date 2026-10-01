"""No-key public/reference discovery feeds for AETHER vNext.

These sources exist to exercise the complete prototype discovery architecture without
pretending reference data is execution-grade. The execution providers remain the
canonical provider buckets; these public sources only populate catalog and scouting
telemetry.

Sources:
- tastyfx public product-details page + ECB daily reference FX rates
- NinjaTrader public margins catalog + CME Group public Product Slate activity
- Nasdaq Trader public symbol directories + Cboe public US-equity symbol data

No source in this module has trading authority.
"""
from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import io
import json
import re
from typing import Iterable, Mapping
import xml.etree.ElementTree as ET

import httpx

from aether_vnext.provider_discovery import DiscoveryInstrument


UTC = timezone.utc
USER_AGENT = (
    "Mozilla/5.0 (compatible; AETHER-Prototype/1.0; "
    "+https://github.com/TyreeCooper/project-aether)"
)

TASTYFX_PRODUCT_DETAILS_URL = (
    "https://www.tastyfx.com/help-and-support/articles/"
    "618850-what-are-tastyfx-s-forex-product-details"
)
ECB_90D_XML_URL = (
    "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
)
NINJATRADER_MARGINS_URL = "https://ninjatrader.com/pricing/margins/"
CME_PRODUCT_SLATE_V2_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/ProductSlate/V2/List"
)
CME_PRODUCT_SLATE_PAGE_URL = "https://www.cmegroup.com/markets/products"
NASDAQ_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
)
NASDAQ_OTHER_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
)
CBOE_SYMBOL_CSV_TEMPLATE = (
    "https://cdn-api.cboe.com/api/us/equities/market-statistics/"
    "symbol-data/{market}/{market}-equities-symbol-data.csv"
)
CBOE_MARKETS = ("bzx", "byx", "edga", "edgx")

_PAIR_RE = re.compile(r"\b([A-Z]{3})\s*/\s*([A-Z]{3})\b")
_KNOWN_TASTYFX_SOURCE_FIXUPS = {
    # Current public product-details article renders this one row as UGBP/HUF.
    # Preserve the public source while normalizing the obvious four-letter typo.
    "UGBP/HUF": "GBP/HUF",
}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "tr":
            self._row = []
        elif normalized in {"td", "th"} and self._row is not None:
            self._cell = []
        elif normalized == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"td", "th"} and self._cell is not None:
            value = " ".join("".join(self._cell).split())
            if self._row is not None:
                self._row.append(unescape(value))
            self._cell = None
        elif normalized == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def html_table_rows(raw_html: str) -> tuple[tuple[str, ...], ...]:
    parser = _TableParser()
    parser.feed(raw_html)
    return tuple(tuple(cell for cell in row) for row in parser.rows)


def _visible_text(raw_html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def extract_tastyfx_pairs(raw_html: str) -> tuple[str, ...]:
    text = _visible_text(raw_html)
    for bad, corrected in _KNOWN_TASTYFX_SOURCE_FIXUPS.items():
        text = text.replace(bad, corrected)
    pairs = {
        f"{base}/{quote}"
        for base, quote in _PAIR_RE.findall(text)
        if base != quote
    }
    return tuple(sorted(pairs))


def parse_ecb_90d_xml(raw_xml: str) -> tuple[tuple[str, dict[str, float]], ...]:
    root = ET.fromstring(raw_xml)
    snapshots: list[tuple[str, dict[str, float]]] = []
    for node in root.iter():
        if not node.tag.endswith("Cube") or "time" not in node.attrib:
            continue
        rates: dict[str, float] = {"EUR": 1.0}
        for child in node:
            currency = child.attrib.get("currency")
            rate = child.attrib.get("rate")
            if not currency or not rate:
                continue
            rates[str(currency).upper()] = float(rate)
        snapshots.append((str(node.attrib["time"]), rates))
    snapshots.sort(key=lambda item: item[0], reverse=True)
    return tuple(snapshots)


def _fx_cross_rate(base: str, quote: str, rates: Mapping[str, float]) -> float | None:
    base_rate = rates.get(base)
    quote_rate = rates.get(quote)
    if base_rate is None or quote_rate is None:
        return None
    if float(base_rate) <= 0 or float(quote_rate) <= 0:
        return None
    return float(quote_rate) / float(base_rate)


def build_tastyfx_reference_universe(
    pairs: Iterable[str],
    ecb_snapshots: tuple[tuple[str, dict[str, float]], ...],
    *,
    observed_at_utc: datetime,
) -> tuple[DiscoveryInstrument, ...]:
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    current = ecb_snapshots[0][1] if ecb_snapshots else {}
    previous = ecb_snapshots[1][1] if len(ecb_snapshots) > 1 else {}

    rows: list[DiscoveryInstrument] = []
    for pair in sorted(set(str(value).strip().upper() for value in pairs)):
        match = _PAIR_RE.fullmatch(pair)
        if match is None:
            continue
        base, quote = match.groups()
        price = _fx_cross_rate(base, quote, current)
        prev = _fx_cross_rate(base, quote, previous)
        change_pct = (
            None
            if price is None or prev is None or prev <= 0
            else ((price - prev) / prev) * 100.0
        )
        rows.append(
            DiscoveryInstrument(
                provider="tastyfx",
                symbol=pair,
                market_data_symbol=pair,
                execution_symbol=None,
                asset_class="fx",
                name=pair,
                active=True,
                price=price,
                open_price=prev,
                high_price=(
                    None if price is None or prev is None else max(price, prev)
                ),
                low_price=(
                    None if price is None or prev is None else min(price, prev)
                ),
                volume=None,
                bid=None,
                ask=None,
                change_pct=change_pct,
                observed_at_utc=observed_at_utc,
                source="tastyfx_public_catalog+ecb_daily_reference",
                feed_class="PUBLIC_REFERENCE_DAILY",
                execution_quality=False,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class NinjaCatalogRow:
    symbol: str
    market: str
    exchange: str
    group: str
    day_margin: float | None
    maintenance_margin: float | None
    initial_margin: float | None


def _money_number(value: object) -> float | None:
    text = str(value or "").replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return float(match.group(0))


def parse_ninjatrader_margin_html(raw_html: str) -> tuple[NinjaCatalogRow, ...]:
    rows = html_table_rows(raw_html)
    out: list[NinjaCatalogRow] = []
    seen: set[str] = set()
    for cells in rows:
        if len(cells) < 7:
            continue
        symbol = cells[0].strip().upper()
        if symbol in {"SYMBOL", ""}:
            continue
        if not re.fullmatch(r"[A-Z0-9]{1,12}", symbol):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(
            NinjaCatalogRow(
                symbol=symbol,
                market=cells[1].strip(),
                exchange=cells[2].strip(),
                group=cells[3].strip(),
                day_margin=_money_number(cells[4]),
                maintenance_margin=_money_number(cells[5]),
                initial_margin=_money_number(cells[6]),
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class CmeActivity:
    symbol: str
    name: str | None
    exchange: str | None
    asset_class: str | None
    volume: float | None
    open_interest: float | None


def _field(row: Mapping[str, object], *names: str) -> object | None:
    lowered = {str(key).lower().replace("_", ""): value for key, value in row.items()}
    for name in names:
        key = name.lower().replace("_", "")
        if key in lowered:
            return lowered[key]
    return None


def _number(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _candidate_mapping_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, Mapping)]
        if rows and any(
            any(
                str(key).lower().replace("_", "") in {
                    "globex", "globexcode", "productcode", "productname",
                    "clearedas", "instrumenttype", "volume", "openinterest",
                }
                for key in row
            )
            for row in rows
        ):
            return rows
        for value in payload:
            nested = _candidate_mapping_rows(value)
            if nested:
                return nested
        return []
    if isinstance(payload, Mapping):
        for preferred in ("products", "results", "data", "items", "productList", "productSlate"):
            if preferred in payload:
                nested = _candidate_mapping_rows(payload[preferred])
                if nested:
                    return nested
        for value in payload.values():
            nested = _candidate_mapping_rows(value)
            if nested:
                return nested
    return []


def parse_cme_product_slate_json(payload: object) -> dict[str, CmeActivity]:
    candidates = _candidate_mapping_rows(payload)
    if not candidates:
        return {}

    out: dict[str, CmeActivity] = {}
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        cleared_as = str(
            _field(raw, "clearedAs", "cleared_as", "instrumentType", "type") or ""
        ).lower()
        if cleared_as and "future" not in cleared_as:
            continue
        symbol = str(
            _field(
                raw,
                "globex",
                "globexCode",
                "globex_code",
                "productCode",
                "product_code",
                "symbol",
            )
            or ""
        ).strip().upper()
        if not symbol or symbol == "-":
            continue
        row = CmeActivity(
            symbol=symbol,
            name=(
                None
                if _field(raw, "productName", "product_name", "name") is None
                else str(_field(raw, "productName", "product_name", "name"))
            ),
            exchange=(
                None
                if _field(raw, "exchange", "exch") is None
                else str(_field(raw, "exchange", "exch"))
            ),
            asset_class=(
                None
                if _field(raw, "assetClass", "asset_class") is None
                else str(_field(raw, "assetClass", "asset_class"))
            ),
            volume=_number(_field(raw, "volume", "vol")),
            open_interest=_number(
                _field(raw, "openInterest", "open_interest", "oi")
            ),
        )
        previous = out.get(symbol)
        if previous is None or (row.volume or 0.0) > (previous.volume or 0.0):
            out[symbol] = row
    return out


def parse_cme_product_slate_html(raw_html: str) -> dict[str, CmeActivity]:
    out: dict[str, CmeActivity] = {}
    for cells in html_table_rows(raw_html):
        if len(cells) < 12:
            continue
        if cells[0].strip().lower() == "product name":
            continue
        cleared_as = cells[10].strip().lower()
        if "future" not in cleared_as:
            continue
        symbol = cells[2].strip().upper()
        if not symbol or symbol == "-":
            continue
        row = CmeActivity(
            symbol=symbol,
            name=cells[0].strip() or None,
            exchange=cells[5].strip() or None,
            asset_class=cells[6].strip() or None,
            volume=_number(cells[11]),
            open_interest=_number(cells[12] if len(cells) > 12 else None),
        )
        out[symbol] = row
    return out


def build_ninjatrader_reference_universe(
    catalog: Iterable[NinjaCatalogRow],
    cme_activity: Mapping[str, CmeActivity],
    *,
    observed_at_utc: datetime,
) -> tuple[DiscoveryInstrument, ...]:
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    rows: list[DiscoveryInstrument] = []
    for item in catalog:
        activity = cme_activity.get(item.symbol)
        rows.append(
            DiscoveryInstrument(
                provider="NinjaTrader",
                symbol=item.symbol,
                market_data_symbol=item.symbol,
                execution_symbol=item.symbol,
                asset_class="future",
                name=item.market,
                product_code=item.symbol,
                active=True,
                price=None,
                open_price=None,
                high_price=None,
                low_price=None,
                volume=None if activity is None else activity.volume,
                open_interest=(
                    None if activity is None else activity.open_interest
                ),
                bid=None,
                ask=None,
                change_pct=None,
                observed_at_utc=observed_at_utc,
                source=(
                    "ninjatrader_public_catalog"
                    if activity is None
                    else "ninjatrader_public_catalog+cme_product_slate"
                ),
                feed_class=(
                    "PUBLIC_CATALOG"
                    if activity is None
                    else "PUBLIC_REFERENCE_DELAYED"
                ),
                execution_quality=False,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class UsListedSecurity:
    symbol: str
    name: str
    exchange: str
    asset_class: str


def parse_nasdaq_listed_file(
    raw_text: str,
    *,
    source_exchange: str,
) -> tuple[UsListedSecurity, ...]:
    reader = csv.DictReader(io.StringIO(raw_text), delimiter="|")
    out: list[UsListedSecurity] = []
    seen: set[str] = set()
    for raw in reader:
        symbol = str(
            raw.get("Symbol")
            or raw.get("ACT Symbol")
            or raw.get("NASDAQ Symbol")
            or ""
        ).strip().upper()
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        if str(raw.get("Test Issue") or "").strip().upper() == "Y":
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        name = str(raw.get("Security Name") or symbol).strip()
        is_etf = str(raw.get("ETF") or "").strip().upper() == "Y"
        out.append(
            UsListedSecurity(
                symbol=symbol,
                name=name,
                exchange=str(raw.get("Exchange") or source_exchange).strip(),
                asset_class="etf" if is_etf else "equity_security",
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class CboeSymbolQuote:
    symbol: str
    volume: float
    bid: float | None
    ask: float | None
    last: float | None


def _normalized_csv_row(raw: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key or "").strip().lower().replace(" ", "").replace("_", ""): value
        for key, value in raw.items()
    }


def parse_cboe_symbol_csv(raw_text: str) -> tuple[CboeSymbolQuote, ...]:
    reader = csv.DictReader(io.StringIO(raw_text))
    out: list[CboeSymbolQuote] = []
    for raw in reader:
        row = _normalized_csv_row(raw)
        symbol = str(row.get("symbol") or row.get("name") or "").strip().upper()
        if not symbol:
            continue
        volume = _number(row.get("volume") or row.get("vol")) or 0.0
        bid = _number(row.get("bidprice") or row.get("bidpx"))
        ask = _number(row.get("askprice") or row.get("askpx"))
        last = _number(row.get("lastprice") or row.get("last"))
        if bid is not None and bid <= 0:
            bid = None
        if ask is not None and ask <= 0:
            ask = None
        if last is not None and last <= 0:
            last = None
        out.append(
            CboeSymbolQuote(
                symbol=symbol,
                volume=float(volume),
                bid=bid,
                ask=ask,
                last=last,
            )
        )
    return tuple(out)


def merge_cboe_symbol_quotes(
    groups: Iterable[Iterable[CboeSymbolQuote]],
) -> dict[str, CboeSymbolQuote]:
    """Merge venue rows while retaining only one aggregate object per symbol."""
    merged: dict[str, CboeSymbolQuote] = {}
    for group in groups:
        for row in group:
            current = merged.get(row.symbol)
            if current is None:
                merged[row.symbol] = row
                continue
            merged[row.symbol] = CboeSymbolQuote(
                symbol=row.symbol,
                volume=float(current.volume) + float(row.volume),
                bid=row.bid if row.bid is not None else current.bid,
                ask=row.ask if row.ask is not None else current.ask,
                last=row.last if row.last is not None else current.last,
            )
    return merged


def build_ibkr_us_equity_reference_universe(
    securities: Iterable[UsListedSecurity],
    quotes: Mapping[str, CboeSymbolQuote],
    *,
    observed_at_utc: datetime,
) -> tuple[DiscoveryInstrument, ...]:
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    rows: list[DiscoveryInstrument] = []
    for security in securities:
        quote = quotes.get(security.symbol)
        rows.append(
            DiscoveryInstrument(
                provider="IBKR",
                symbol=security.symbol,
                market_data_symbol=security.symbol,
                execution_symbol=security.symbol,
                asset_class=security.asset_class,
                name=security.name,
                active=True,
                price=None if quote is None else quote.last,
                open_price=None,
                high_price=None,
                low_price=None,
                volume=None if quote is None else quote.volume,
                open_interest=None,
                bid=None if quote is None else quote.bid,
                ask=None if quote is None else quote.ask,
                change_pct=None,
                observed_at_utc=observed_at_utc,
                source=(
                    "nasdaq_trader_public_catalog"
                    if quote is None
                    else "nasdaq_trader_public_catalog+cboe_public_symbol_data"
                ),
                feed_class=(
                    "PUBLIC_CATALOG"
                    if quote is None
                    else "PUBLIC_REFERENCE_INTRADAY"
                ),
                execution_quality=False,
            )
        )
    return tuple(rows)


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def fetch_tastyfx_public_universe(
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[DiscoveryInstrument, ...]:
    owned = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        catalog_html, ecb_xml = await asyncio.gather(
            _get_text(http, TASTYFX_PRODUCT_DETAILS_URL),
            _get_text(http, ECB_90D_XML_URL),
        )
        pairs = extract_tastyfx_pairs(catalog_html)
        if len(pairs) < 25:
            raise RuntimeError(
                f"tastyfx_public_catalog_too_small:{len(pairs)}"
            )
        ecb = parse_ecb_90d_xml(ecb_xml)
        if not ecb:
            raise RuntimeError("ecb_reference_rates_empty")
        return build_tastyfx_reference_universe(
            pairs,
            ecb,
            observed_at_utc=datetime.now(UTC),
        )
    finally:
        if owned:
            await http.aclose()


async def _fetch_cme_activity(client: httpx.AsyncClient) -> dict[str, CmeActivity]:
    try:
        response = await client.get(
            CME_PRODUCT_SLATE_V2_URL,
            params={
                "pageNumber": 1,
                # CME's public Product Slate UI is capped at 500 rows. Asking
                # for 5,000 caused Azure-side read timeouts and is unnecessary:
                # Top-25 focus only needs the most active supported futures.
                "pageSize": 500,
                "sortAsc": "false",
                "sortField": "oi",
                "searchString": "",
            },
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.8",
                "Referer": CME_PRODUCT_SLATE_PAGE_URL,
            },
        )
        response.raise_for_status()
        activity = parse_cme_product_slate_json(response.json())
        if len(activity) >= 25:
            return activity
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        pass

    response = await client.get(
        CME_PRODUCT_SLATE_PAGE_URL,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    response.raise_for_status()
    activity = parse_cme_product_slate_html(response.text)
    if len(activity) < 25:
        raise RuntimeError(
            f"cme_public_activity_too_small:{len(activity)}"
        )
    return activity


async def fetch_ninjatrader_public_universe(
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[DiscoveryInstrument, ...]:
    owned = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        margins_html, activity = await asyncio.gather(
            _get_text(http, NINJATRADER_MARGINS_URL),
            _fetch_cme_activity(http),
        )
        catalog = parse_ninjatrader_margin_html(margins_html)
        if len(catalog) < 25:
            raise RuntimeError(
                f"ninjatrader_public_catalog_too_small:{len(catalog)}"
            )
        rows = build_ninjatrader_reference_universe(
            catalog,
            activity,
            observed_at_utc=datetime.now(UTC),
        )
        activity_rows = sum(
            1 for row in rows
            if row.volume is not None or row.open_interest is not None
        )
        if activity_rows < 25:
            raise RuntimeError(
                f"ninjatrader_reference_activity_too_small:{activity_rows}"
            )
        return rows
    finally:
        if owned:
            await http.aclose()


async def fetch_ibkr_us_equity_public_universe(
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[DiscoveryInstrument, ...]:
    owned = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        # The two symbol directories are modest; fetch them together.
        listed_text, other_text = await asyncio.gather(
            _get_text(http, NASDAQ_LISTED_URL),
            _get_text(http, NASDAQ_OTHER_LISTED_URL),
        )
        nasdaq = parse_nasdaq_listed_file(
            listed_text,
            source_exchange="NASDAQ",
        )
        other = parse_nasdaq_listed_file(
            other_text,
            source_exchange="OTHER",
        )
        del listed_text, other_text

        by_symbol: dict[str, UsListedSecurity] = {
            row.symbol: row for row in (*nasdaq, *other)
        }
        if len(by_symbol) < 1000:
            raise RuntimeError(
                f"us_equity_public_catalog_too_small:{len(by_symbol)}"
            )

        # Cboe all-symbol files can be large. Process one venue at a time and
        # discard each raw CSV immediately instead of buffering all four.
        quotes: dict[str, CboeSymbolQuote] = {}
        for market in CBOE_MARKETS:
            text = await _get_text(
                http,
                CBOE_SYMBOL_CSV_TEMPLATE.format(market=market),
            )
            venue_rows = parse_cboe_symbol_csv(text)
            del text
            quotes = merge_cboe_symbol_quotes(
                (quotes.values(), venue_rows),
            )
            del venue_rows

        return build_ibkr_us_equity_reference_universe(
            tuple(by_symbol[symbol] for symbol in sorted(by_symbol)),
            quotes,
            observed_at_utc=datetime.now(UTC),
        )
    finally:
        if owned:
            await http.aclose()
