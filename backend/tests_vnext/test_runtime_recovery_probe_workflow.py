from __future__ import annotations

from pathlib import Path


def _workflow() -> str:
    root = Path(__file__).resolve().parents[2]
    return (
        root
        / ".github"
        / "workflows"
        / "aether-vnext-runtime-recovery-probe.yml"
    ).read_text(encoding="utf-8")


def test_continuity_probe_takes_two_read_only_runtime_snapshots() -> None:
    workflow = _workflow()

    assert "snapshot first" in workflow
    assert "sleep 90" in workflow
    assert "snapshot second" in workflow
    assert "/api/v1/health" in workflow
    assert "/api/v1/vnext/ingress-runtime" in workflow
    assert "/api/v1/vnext/strategy-runtime" in workflow
    assert "/api/v1/vnext/floor" in workflow
    assert "curl --silent --show-error" in workflow
    assert " -X POST " not in workflow
    assert " -X PUT " not in workflow
    assert " -X PATCH " not in workflow
    assert " -X DELETE " not in workflow


def test_continuity_probe_requires_real_cycle_progress_and_stable_revision() -> None:
    workflow = _workflow()

    assert "second_revision == first_revision" in workflow
    assert "second_ingress_cycles > first_ingress_cycles" in workflow
    assert "second_strategy_cycles > first_strategy_cycles" in workflow
    assert "second_observations >= first_observations" in workflow
    assert 'row.get("forward_paper_observation_recorded") is True' in workflow


def test_continuity_probe_preserves_prototype_safety_boundary() -> None:
    workflow = _workflow()

    assert 'health.get("paper_mode") is True' in workflow
    assert 'health.get("live_blocked") is True' in workflow
    assert 'mode.get("paper_only") is True' in workflow
    assert 'mode.get("live_blocked") is True' in workflow
    assert 'result.get("phase18_evidence") is False' in workflow
    assert "aether-prototype-new-system-test-001" in workflow
    assert "10000.0" in workflow
    assert "actions/upload-artifact@v4" in workflow
