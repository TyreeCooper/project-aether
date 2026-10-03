from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_shadow_http_probe.py"
    )
    spec = importlib.util.spec_from_file_location("shadow_http_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_shadow_http_probe_verifies_coexistence_and_get_only_floor() -> None:
    module = _load_script()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health" and request.method == "GET":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/vnext/floor":
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "mode": {
                            "paper_only": True,
                            "live_blocked": True,
                        }
                    },
                )
            return httpx.Response(405)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    ) as client:
        result = await module.probe_shadow_http(
            base_url="https://example.test",
            client=client,
        )

    assert result["legacy"]["available"] is True
    assert result["vnext_floor"]["available"] is True
    assert result["vnext_floor"]["paper_only"] is True
    assert result["vnext_floor"]["live_blocked"] is True
    assert result["mutation_transport_absent"] is True
    assert result["http_shadow_verified"] is True
    assert result["process_runtime_observation"]["verified"] is False
    assert result["authority"]["may_switch_runtime"] is False


@pytest.mark.asyncio
async def test_shadow_http_probe_fails_closed_on_vnext_503() -> None:
    module = _load_script()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/vnext/floor":
            if request.method == "GET":
                return httpx.Response(503, json={"detail": "vNext unavailable"})
            return httpx.Response(405)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await module.probe_shadow_http(
            base_url="https://example.test",
            client=client,
        )

    assert result["legacy"]["available"] is True
    assert result["vnext_floor"]["available"] is False
    assert result["http_shadow_verified"] is False


@pytest.mark.asyncio
async def test_shadow_http_probe_requires_every_mutation_method_to_be_rejected() -> None:
    module = _load_script()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/vnext/floor":
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "mode": {
                            "paper_only": True,
                            "live_blocked": True,
                        }
                    },
                )
            if request.method == "PATCH":
                return httpx.Response(200)
            return httpx.Response(405)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await module.probe_shadow_http(
            base_url="https://example.test",
            client=client,
        )

    assert result["mutation_methods"]["PATCH"] == 200
    assert result["mutation_transport_absent"] is False
    assert result["http_shadow_verified"] is False


def test_shadow_probe_uses_existing_canonical_paths() -> None:
    module = _load_script()
    assert module.LEGACY_HEALTH_PATH == "/api/v1/health"
    assert module.VNEXT_FLOOR_PATH == "/api/v1/vnext/floor"
