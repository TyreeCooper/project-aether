from __future__ import annotations

from pathlib import Path

from aether_vnext.store import VNextStore


def test_unchecked_open_reservation_is_not_public_runtime_api() -> None:
    assert not hasattr(VNextStore, "reserve_order_intent")
    assert hasattr(VNextStore, "reserve_risk_checked_open_intent")
    assert hasattr(VNextStore, "_reserve_order_intent_after_admission")


def test_no_other_vnext_runtime_module_calls_private_reservation_primitive() -> None:
    package = Path(__file__).resolve().parents[1] / "aether_vnext"
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        if path.name == "store.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "_reserve_order_intent_after_admission(" in source:
            offenders.append(path.name)
    assert offenders == []


def test_checked_admission_is_the_only_public_open_reservation_entrypoint() -> None:
    public = [
        name
        for name in dir(VNextStore)
        if "reserve" in name.lower()
        and "order_intent" in name.lower()
        and not name.startswith("_")
    ]
    assert public == ["reserve_risk_checked_open_intent"]
