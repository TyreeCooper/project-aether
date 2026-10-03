from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_kraken_freshness_probe.py"
)
UTC = timezone.utc
T0 = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_kraken_freshness_probe_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _batch(index: int):
    quotes = tuple(
        SimpleNamespace(
            asset_id=asset_id,
            exchange_ts=T0 + timedelta(seconds=index, milliseconds=offset),
            received_ts=T0 + timedelta(
                seconds=index,
                milliseconds=offset + 25,
            ),
        )
        for asset_id, offset in (("btc", 0), ("eth", 10))
    )
    return SimpleNamespace(status_system="online", quotes=quotes)


@pytest.mark.asyncio
async def test_probe_measures_real_timing_shape_without_selecting_policy() -> None:
    module = _module()
    calls = 0

    async def fetcher(*, assets, timeout_s):
        nonlocal calls
        assert assets == ("btc", "eth")
        assert timeout_s == 5.0
        batch = _batch(calls)
        calls += 1
        return batch

    payload = await module.collect_kraken_freshness_evidence(
        assets=("btc", "eth"),
        rounds=3,
        timeout_s=5.0,
        pause_s=0.0,
        fetcher=fetcher,
    )

    assert calls == 3
    assert payload["sample_rounds"] == 3
    assert payload["policy_selected"] is False
    assert payload["stale_threshold_ms"] is None
    assert payload["database_mutation"] is False
    assert payload["authentication_required"] is False
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["assets"]["btc"]["transport_latency"]["p99_ms"] == 25
    assert payload["assets"]["eth"]["transport_latency"]["p99_ms"] == 25
    assert payload["assets"]["btc"]["stale_threshold_ms"] is None


@pytest.mark.asyncio
async def test_probe_fails_if_provider_timestamp_is_absent() -> None:
    module = _module()

    async def fetcher(*, assets, timeout_s):
        return SimpleNamespace(
            status_system="online",
            quotes=tuple(
                SimpleNamespace(
                    asset_id=asset_id,
                    exchange_ts=None if asset_id == "btc" else T0,
                    received_ts=T0 + timedelta(milliseconds=30),
                )
                for asset_id in assets
            ),
        )

    with pytest.raises(RuntimeError, match="lacks provider timestamp: btc"):
        await module.collect_kraken_freshness_evidence(
            assets=("btc", "eth"),
            rounds=2,
            timeout_s=5.0,
            pause_s=0.0,
            fetcher=fetcher,
        )


def test_probe_is_secret_free_and_db_free() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "open_vnext_engine" not in source
    assert "VNextStore" not in source
    assert "os.getenv" not in source
    assert "Authorization" not in source
