"""Desk wallet survives deploys. Same idea as Kraken funding: cash does not reset."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def desk_path() -> Path:
    override = os.getenv("DESK_STATE_PATH")
    if override:
        return Path(override)
    home = Path("/home")
    if home.exists() and os.access(home, os.W_OK):
        path = home / "aether" / "desk_wallet.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path = Path("data") / "desk_wallet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_desk() -> dict[str, Any] | None:
    path = desk_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_desk(payload: dict[str, Any]) -> None:
    path = desk_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
