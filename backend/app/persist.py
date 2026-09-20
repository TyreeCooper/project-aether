"""Durable paper-state file. On Azure App Service use /home (survives restarts)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def state_path() -> Path:
    override = os.getenv("PAPER_STATE_PATH")
    if override:
        return Path(override)
    home = Path("/home")
    if home.exists() and os.access(home, os.W_OK):
        path = home / "aether" / "paper_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path = Path("data") / "paper_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state() -> dict[str, Any] | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_state(payload: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
