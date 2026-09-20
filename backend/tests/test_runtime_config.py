import pytest

from app.engine import PaperEngine


@pytest.mark.asyncio
async def test_runtime_config_requires_offline_flat(tmp_path, monkeypatch):
    engine = PaperEngine()
    engine.state = "IDLE"
    result = await engine.update_config({})
    assert result["ok"] is False
    assert result["error"] == "config_requires_offline_flat"


@pytest.mark.asyncio
async def test_runtime_config_validates_ma_order():
    engine = PaperEngine()
    engine.state = "OFFLINE"
    engine.btc = 0
    result = await engine.update_config({"short_ma": 21, "long_ma": 8})
    assert result["ok"] is False
    assert result["error"] == "long_ma_must_exceed_short_ma"
