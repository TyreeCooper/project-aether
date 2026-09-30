from __future__ import annotations

import pytest

from app.vnext_runtime_mode import (
    configured_vnext_runtime_only,
    validate_vnext_runtime_only_environment,
)


def test_vnext_runtime_only_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_RUNTIME_ONLY", raising=False)
    assert configured_vnext_runtime_only() is False
    validate_vnext_runtime_only_environment()


def test_vnext_runtime_only_requires_burnin(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_RUNTIME_ONLY", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    assert configured_vnext_runtime_only() is True
    with pytest.raises(RuntimeError, match="only run in burnin"):
        validate_vnext_runtime_only_environment()


def test_vnext_runtime_only_accepts_burnin(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_RUNTIME_ONLY", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "burnin")
    validate_vnext_runtime_only_environment()
