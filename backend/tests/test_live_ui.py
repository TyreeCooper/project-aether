from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_live_trades_surface_is_first_class_navigation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="view-live"' in html
    assert 'data-route="live"' in html
    assert 'id="liveTradeCards"' in html
    assert 'id="liveEvents"' in html
    assert 'id="floorLiveStrip"' in html


def test_live_ui_uses_canonical_live_trade_endpoint_and_local_timer():
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert "/api/v1/desk/live-trades" in js
    assert "liveDuration" in js
    assert "duration_seconds" in js
    assert "open_pnl_usd" in js
    assert "management_state" in js


def test_blotter_renders_round_trip_duration_fields():
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert "realized_pnl_usd" in js
    assert "entry_price" in js
    assert "exit_price" in js
    assert "duration_seconds" in js
    assert "exit_reason" in js


def test_live_trade_styles_are_present():
    css = (STATIC / "aether-app.css").read_text(encoding="utf-8")
    assert ".live-strip" in css
    assert ".live-trade-card" in css
    assert ".live-duration" in css
    assert ".event-stream" in css
