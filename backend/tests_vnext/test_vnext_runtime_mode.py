from __future__ import annotations

import pytest

from app.vnext_runtime_mode import configured_vnext_runtime_only, validate_vnext_runtime_only_environment


def test_sandbox_is_always_vnext_runtime_only(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("AETHER_VNEXT_RUNTIME_ONLY", raising=False)
    assert configured_vnext_runtime_only() is True
    validate_vnext_runtime_only_environment()


def test_non_sandbox_environment_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    assert configured_vnext_runtime_only() is False
    with pytest.raises(RuntimeError, match="sandbox"):
        validate_vnext_runtime_only_environment()
