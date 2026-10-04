from __future__ import annotations

import asyncio

import pytest

from aether_vnext.tape_supervisor import TapeSupervisor


@pytest.mark.asyncio
async def test_tape_supervisor_stays_paper_only_and_runs_repeated_cycles() -> None:
    calls = 0
    reached = asyncio.Event()

    async def cycle():
        nonlocal calls
        calls += 1
        if calls >= 2:
            reached.set()
        return {"paper_only": True, "live_blocked": True}

    supervisor = TapeSupervisor(cycle_runner=cycle, interval_seconds=2.0)
    await supervisor.start()
    await asyncio.wait_for(reached.wait(), timeout=5.0)
    status = supervisor.status(enabled=True)
    await supervisor.stop()

    assert status.paper_only is True
    assert status.live_blocked is True
    assert status.cycle_count >= 2
    assert status.last_error is None
