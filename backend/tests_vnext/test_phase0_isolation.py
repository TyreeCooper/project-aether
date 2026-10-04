from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import aether_vnext


BACKEND = Path(__file__).resolve().parents[1]
VNEXT = BACKEND / "aether_vnext"


def _legacy_imports() -> list[str]:
    violations: list[str] = []
    for path in sorted(VNEXT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app" or alias.name.startswith("app."):
                        violations.append(f"{path.relative_to(BACKEND)} -> import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "app" or module.startswith("app."):
                    violations.append(f"{path.relative_to(BACKEND)} -> from {module}")
    return violations


def test_vnext_source_does_not_import_legacy_app_package() -> None:
    assert _legacy_imports() == []


def test_vnext_runtime_contract_keeps_live_hard_blocked() -> None:
    contract = aether_vnext.runtime_contract()
    assert contract["runtime_namespace"] == "aether_vnext"
    assert contract["spec_bundle"] == "firm-v5.0+playbook-v1.4+precode-v1.0"
    assert contract["paper_only"] is True
    assert contract["live_blocked"] is True
    assert contract["legacy_compatibility_required"] is False


def test_clean_vnext_import_does_not_load_legacy_runtime() -> None:
    script = """
import sys
import aether_vnext

contract = aether_vnext.runtime_contract()
assert contract["paper_only"] is True
assert contract["live_blocked"] is True
legacy = sorted(name for name in sys.modules if name == "app" or name.startswith("app."))
assert legacy == [], legacy
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
