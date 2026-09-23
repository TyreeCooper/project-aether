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
    assert "<th>Trade Duration</th>" in js
    assert 'String(h).padStart(2,"0")' in js
    assert 'String(m).padStart(2,"0")' in js
    assert 'String(sec).padStart(2,"0")' in js
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


def test_trade_list_sort_and_filter_controls_are_present():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    for control_id in (
        "floorSort",
        "fillSort",
        "fillSideFilter",
        "liveSort",
        "liveSortDir",
        "liveSideFilter",
        "liveModeFilter",
        "blotterSort",
        "blotterSortDir",
        "blotterSideFilter",
        "blotterModeFilter",
    ):
        assert f'id="{control_id}"' in html
    assert "sortRows" in js
    assert "pnlClass" in js


def test_floor_exposes_margin_and_bank_labels():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert "Margin Used" in html
    assert "Starting Bank" in js
    assert "Free Margin" in js
    assert "Gross Exposure" in js
    assert "Test Overflow" in js



def test_operator_ui_is_server_verified_and_read_only_until_connected():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert 'id="disconnectOperator"' in html
    assert "operatorAuthenticated:false" in js
    assert "authConfigured:false" in js
    assert "/api/v1/auth/status" in js
    assert "renderOperatorControls" in js
    assert "sessionStorage" in js
    assert 'localStorage.removeItem("aether-operator-token")' in js
    assert 'el.value=""' in js
    assert 'el.disabled=connected||!configured' in js
    assert 'const armDisabled=!connected||armed' in js
    assert 'disarmDisabled=!connected||!armed' in js
    assert 'if(!state.operatorAuthenticated){toast("Operator authentication required.")' in js



def test_engine_exposes_operator_gated_execution_matrix_validation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert 'id="runExecutionMatrix"' in html
    assert 'id="executionMatrix"' in html
    assert 'id="matrixRunBadge"' in html
    assert "/api/v1/desk/execution-matrix" in js
    assert "/api/v1/desk/execution-matrix/run" in js
    assert "production_wallet_unchanged" in js
    assert '"runExecutionMatrix"' in js



def test_load_002_release_marker_and_cache_busted_assets_are_present():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "aether-app.js").read_text(encoding="utf-8")
    assert 'content="AETHER-LOAD-002-EXP-R1"' in html
    assert "/static/aether-app.css?v=AETHER-LOAD-002-EXP-R1" in html
    assert "/static/aether-app.js?v=AETHER-LOAD-002-EXP-R1" in html
    assert 'id="settingsLoadBadge"' in html
    assert 'id="settingsLoadStatus"' in html
    assert "Runtime safety" in js
    assert "Observed books" in js
