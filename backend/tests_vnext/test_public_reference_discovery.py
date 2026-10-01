from datetime import datetime, timezone
import io

from openpyxl import Workbook

from aether_vnext.public_reference_discovery import (
    build_ibkr_us_equity_reference_universe,
    build_ninjatrader_reference_universe,
    build_tastyfx_reference_universe,
    extract_tastyfx_pairs,
    merge_cboe_symbol_quotes,
    parse_cboe_symbol_csv,
    parse_cme_daily_volume_xlsx,
    parse_cme_product_slate_json,
    parse_ecb_90d_xml,
    parse_nasdaq_listed_file,
    parse_ninjatrader_margin_html,
)


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_tastyfx_catalog_extracts_public_pairs_and_normalizes_source_typo() -> None:
    html = """
    <table>
      <tr><td>EUR/USD</td><td>0.8</td></tr>
      <tr><td>USD/JPY</td><td>0.8</td></tr>
      <tr><td>UGBP/HUF</td><td>30</td></tr>
    </table>
    """
    assert extract_tastyfx_pairs(html) == ("EUR/USD", "GBP/HUF", "USD/JPY")


def test_ecb_cross_rates_build_reference_fx_universe() -> None:
    xml = """<?xml version="1.0"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
      xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube><Cube time="2026-09-30">
        <Cube currency="USD" rate="1.20"/>
        <Cube currency="JPY" rate="180.00"/>
        <Cube currency="GBP" rate="0.85"/>
      </Cube>
      <Cube time="2026-09-29">
        <Cube currency="USD" rate="1.10"/>
        <Cube currency="JPY" rate="176.00"/>
        <Cube currency="GBP" rate="0.84"/>
      </Cube></Cube>
    </gesmes:Envelope>
    """
    snapshots = parse_ecb_90d_xml(xml)
    rows = build_tastyfx_reference_universe(
        ("EUR/USD", "USD/JPY", "USD/CNH"),
        snapshots,
        observed_at_utc=NOW,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["EUR/USD"].price == 1.2
    assert by_symbol["USD/JPY"].price == 150.0
    assert by_symbol["EUR/USD"].change_pct is not None
    assert by_symbol["USD/CNH"].price is None
    assert by_symbol["EUR/USD"].feed_class == "PUBLIC_REFERENCE_DAILY"
    assert by_symbol["EUR/USD"].execution_quality is False


def test_ninjatrader_public_margin_table_and_cme_activity_join() -> None:
    html = """
    <table>
      <tr><th>Symbol</th><th>Market</th><th>Exchange</th><th>Group</th>
          <th>Day</th><th>Maintenance</th><th>Initial</th></tr>
      <tr><td>MES</td><td>Micro E-mini S&P 500</td><td>CME</td>
          <td>Micro Indices</td><td>$50.00</td><td>$2600.00</td><td>$2860.00</td></tr>
      <tr><td>MGC</td><td>E-Micro Gold</td><td>COMEX</td>
          <td>Metals</td><td>$200.00</td><td>$2200.00</td><td>$2400.00</td></tr>
    </table>
    """
    catalog = parse_ninjatrader_margin_html(html)
    assert {row.symbol for row in catalog} == {"MES", "MGC"}

    activity = parse_cme_product_slate_json({
        "products": [
            {
                "productName": "Micro E-mini S&P 500 Futures",
                "globex": "MES",
                "exchange": "CME",
                "assetClass": "Equities",
                "clearedAs": "Futures",
                "volume": "1,234,567",
                "openInterest": "2,345,678",
            }
        ]
    })
    rows = build_ninjatrader_reference_universe(
        catalog,
        activity,
        observed_at_utc=NOW,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["MES"].volume == 1234567.0
    assert by_symbol["MES"].open_interest == 2345678.0
    assert by_symbol["MES"].feed_class == "PUBLIC_REFERENCE_DELAYED"
    assert by_symbol["MGC"].feed_class == "PUBLIC_CATALOG"


def test_nasdaq_catalog_and_cboe_quotes_build_ibkr_us_equity_universe() -> None:
    listed = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N
TEST|Test Security|Q|Y|N|100|N|N
File Creation Time: 202610011200|||||||
"""
    securities = parse_nasdaq_listed_file(
        listed,
        source_exchange="NASDAQ",
    )
    assert {row.symbol for row in securities} == {"AAPL", "QQQ"}
    assert next(row for row in securities if row.symbol == "QQQ").asset_class == "etf"

    csv_a = """Symbol,Volume,Matched,Routed,Bid Size,Bid Price,Ask Size,Ask Price,Last Price
AAPL,1000,900,100,100,199.90,200,200.10,200.00
QQQ,500,450,50,50,499.80,60,500.20,500.00
"""
    csv_b = """Symbol,Volume,Matched,Routed,Bid Size,Bid Price,Ask Size,Ask Price,Last Price
AAPL,2000,1900,100,200,199.95,300,200.05,200.01
"""
    merged = merge_cboe_symbol_quotes([
        parse_cboe_symbol_csv(csv_a),
        parse_cboe_symbol_csv(csv_b),
    ])
    assert merged["AAPL"].volume == 3000.0
    assert merged["AAPL"].bid == 199.95

    rows = build_ibkr_us_equity_reference_universe(
        securities,
        merged,
        observed_at_utc=NOW,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["AAPL"].price == 200.01
    assert by_symbol["AAPL"].volume == 3000.0
    assert by_symbol["AAPL"].feed_class == "PUBLIC_REFERENCE_INTRADAY"
    assert by_symbol["AAPL"].execution_quality is False



def test_cboe_incremental_merge_keeps_one_aggregate_per_symbol() -> None:
    first = parse_cboe_symbol_csv(
        "Symbol,Volume,Bid Price,Ask Price,Last Price\n"
        "AAPL,1000,199.90,200.10,200.00\n"
        "MSFT,500,399.90,400.10,400.00\n"
    )
    second = parse_cboe_symbol_csv(
        "Symbol,Volume,Bid Price,Ask Price,Last Price\n"
        "AAPL,2000,199.95,200.05,200.01\n"
    )
    merged = merge_cboe_symbol_quotes((first, second))
    assert set(merged) == {"AAPL", "MSFT"}
    assert merged["AAPL"].volume == 3000.0
    assert merged["AAPL"].bid == 199.95
    assert merged["AAPL"].ask == 200.05
    assert merged["AAPL"].last == 200.01



def test_cme_daily_volume_xlsx_maps_ninjatrader_product_codes() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Daily Volume"
    sheet.append([
        "Exchange",
        "Product Code",
        "Product Name",
        "Total Volume",
        "Open Interest",
    ])
    sheet.append(["CME", "MES", "Micro E-mini S&P 500", 1234567, 2345678])
    sheet.append(["COMEX", "MGC", "Micro Gold", 54321, 65432])
    sheet.append(["CME", "IGNORED", "Ignored", 9999999, 9999999])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    activity = parse_cme_daily_volume_xlsx(
        buffer.getvalue(),
        product_codes=("MES", "MGC"),
    )
    assert set(activity) == {"MES", "MGC"}
    assert activity["MES"].volume == 1234567.0
    assert activity["MES"].open_interest == 2345678.0
    assert activity["MGC"].exchange == "COMEX"


def test_cme_daily_volume_xlsx_fallback_finds_exact_product_code_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Report generated", "2026-10-01"])
    sheet.append(["MES", "Micro E-mini S&P 500", 100, 250000])
    sheet.append(["MGC", "Micro Gold", 50, 80000])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    activity = parse_cme_daily_volume_xlsx(
        buffer.getvalue(),
        product_codes=("MES", "MGC"),
    )
    assert activity["MES"].volume == 250000.0
    assert activity["MGC"].volume == 80000.0
