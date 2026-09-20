from pathlib import Path

from app import persist


def test_save_and_load(tmp_path, monkeypatch):
    path = tmp_path / "paper_state.json"
    monkeypatch.setenv("PAPER_STATE_PATH", str(path))
    persist.save_state({"usd": 9999.0, "btc": 0.01})
    loaded = persist.load_state()
    assert loaded["usd"] == 9999.0
    assert loaded["btc"] == 0.01
    assert Path(path).exists()
