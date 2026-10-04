"""Read immutable build identity embedded into a vNext deployment package."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("build_manifest.json")


def load_build_info(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, str | None]:
    if not path.exists():
        return {
            "source_revision": None,
            "package_built_at_utc": None,
        }

    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("vNext build manifest must contain a JSON object")

    revision = payload.get("source_revision")
    built_at = payload.get("package_built_at_utc")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("vNext build manifest source_revision is required")
    if len(revision.strip()) != 40:
        raise ValueError("vNext build manifest source_revision must be a full SHA")
    if not isinstance(built_at, str) or not built_at.strip():
        raise ValueError("vNext build manifest package_built_at_utc is required")

    parsed = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(
            "vNext build manifest package_built_at_utc must be timezone-aware"
        )

    return {
        "source_revision": revision.strip(),
        "package_built_at_utc": built_at.strip(),
    }
