from __future__ import annotations

from pathlib import Path

import pytest

from aether_vnext.build_info import load_build_info


def test_build_info_defaults_to_unknown_when_not_packaged(tmp_path: Path) -> None:
    result = load_build_info(tmp_path / "missing.json")
    assert result == {
        "source_revision": None,
        "package_built_at_utc": None,
    }


def test_build_info_loads_exact_revision_and_build_time(tmp_path: Path) -> None:
    path = tmp_path / "build.json"
    path.write_text(
        '{"source_revision":"0123456789012345678901234567890123456789",'
        '"package_built_at_utc":"2026-09-29T23:35:00+00:00"}',
        encoding="utf-8",
    )
    result = load_build_info(path)
    assert result["source_revision"] == "0123456789012345678901234567890123456789"
    assert result["package_built_at_utc"] == "2026-09-29T23:35:00+00:00"


def test_build_info_rejects_noncanonical_revision(tmp_path: Path) -> None:
    path = tmp_path / "build.json"
    path.write_text(
        '{"source_revision":"short",'
        '"package_built_at_utc":"2026-09-29T23:35:00+00:00"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="full SHA"):
        load_build_info(path)
