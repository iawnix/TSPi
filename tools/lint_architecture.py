#!/usr/bin/env python3
"""Enforce the Python package ownership boundaries.

This check is intentionally source based.  It prevents a new implementation
from silently recreating the removed ``tspi_runtime`` subpackages while the
single wheel continues to ship several namespaces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_SUBPACKAGE = re.compile(
    r"\btspi_runtime\.(?:backends|analysis|remote|platforms|structures|reaction|pyscf|workspace|providers|io|path_safety|calculation_contracts|runtime)\b"
)


def _python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def check() -> list[str]:
    errors: list[str] = []
    old_roots = [
        ROOT / "packages" / "tspi-runtime" / "tspi_runtime" / name
        for name in ("backends", "analysis", "remote", "platforms", "structures", "reaction", "pyscf", "workspace", "providers", "io.py", "path_safety.py", "calculation_contracts.py", "runtime")
    ]
    for path in old_roots:
        if path.exists() and (path.is_file() or any(path.rglob("*.py"))):
            errors.append(f"removed tspi_runtime implementation remains: {path.relative_to(ROOT)}")

    state_root = ROOT / "packages" / "research-state" / "research_state"
    compute_root = ROOT / "packages" / "research-compute" / "research_compute"
    for path in _python_files(state_root):
        text = path.read_text(encoding="utf-8")
        if "chemical_runtime" in text or "research_compute" in text or re.search(r"\btspi_runtime\b", text):
            errors.append(f"research_state imports a non-State namespace: {path.relative_to(ROOT)}")
    for path in _python_files(compute_root):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\btspi_runtime\b", text):
            errors.append(f"research_compute imports tspi_runtime: {path.relative_to(ROOT)}")
        if re.search(r"\bchemical_runtime\b", text):
            errors.append(f"research_compute imports a Chemistry implementation: {path.relative_to(ROOT)}")

    for root in (ROOT / "packages", ROOT / "extensions", ROOT / "apps", ROOT / "scripts", ROOT / "tools"):
        for path in _python_files(root):
            text = path.read_text(encoding="utf-8")
            if OLD_SUBPACKAGE.search(text):
                errors.append(f"removed tspi_runtime subpackage reference: {path.relative_to(ROOT)}")
    required = (
        ROOT / "packages" / "tspi-foundation" / "tspi_foundation" / "io.py",
        ROOT / "packages" / "tspi-provider-runtime" / "tspi_provider_runtime" / "protocol.py",
        ROOT / "packages" / "tspi-bootstrap" / "tspi_bootstrap" / "launcher.py",
        ROOT / "packages" / "research-compute" / "research_compute" / "remote" / "lifecycle.py",
        ROOT / "extensions" / "chemical" / "providers" / "chemical_runtime" / "analysis" / "engine.py",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"canonical implementation is missing: {path.relative_to(ROOT)}")

    # Pi SDK is the only production Agent Runtime. Keep runtime selection
    # installation-owned and prevent the removed standalone Compute/Review
    # session loops from returning.
    for relative in (
        Path("packages/agent-runtime/agents/compute") / "runtime.ts",
        Path("packages/agent-runtime/agents/review") / "runtime.ts",
    ):
        path = ROOT / relative
        if path.exists():
            errors.append(f"duplicate Pi sub-agent runtime remains: {relative}")
    forbidden_runtime_markers = (
        "RESEARCH_AGENT_" + "RUNTIME_MODULE",
        "RESEARCH_AGENT_" + "KERNEL_MODULE",
        "load_pi_" + "runtime(",
    )
    for root in (ROOT / "apps", ROOT / "packages", ROOT / "scripts"):
        for path in sorted(root.rglob("*.mjs")):
            if any(part in {"node_modules", ".git"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden_runtime_markers:
                if marker in text:
                    errors.append(f"removed alternate Pi runtime boundary {marker!r}: {path.relative_to(ROOT)}")
    app_server = ROOT / "apps" / "app-server" / "pi-app-server.mjs"
    if "source-root" in app_server.read_text(encoding="utf-8"):
        errors.append("pi-app-server exposes a replaceable source-root option")
    return errors


def main() -> int:
    errors = check()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("architecture boundaries: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
