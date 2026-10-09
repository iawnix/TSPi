#!/usr/bin/env python3
"""Enforce package ownership and the single production runtime boundary.

This check is intentionally source based.  It prevents a new implementation
from silently recreating the removed ``research_agent.application`` subpackages while the
single wheel ships one research_agent namespace.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from package_inventory import RETIRED_RUNTIME_PATHS

OLD_SUBPACKAGE = re.compile(
    r"\bresearch_agent_runtime\.(?:backends|analysis|remote|platforms|structures|reaction|pyscf|workspace|providers|io|path_safety|calculation_contracts|runtime)\b"
)


def _python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def check() -> list[str]:
    errors: list[str] = []
    old_roots = [
        ROOT / "backend" / "src" / "research_agent" / "application" / name
        for name in ("backends", "analysis", "remote", "platforms", "structures", "reaction", "pyscf", "workspace", "providers", "io.py", "path_safety.py", "calculation_contracts.py", "runtime")
    ]
    for path in old_roots:
        if path.exists() and (path.is_file() or any(path.rglob("*.py"))):
            errors.append(f"removed research_agent.application implementation remains: {path.relative_to(ROOT)}")

    memory_root = ROOT / "backend" / "src" / "research_agent" / "research"
    for path in _python_files(memory_root):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?:from|import)\s+(?:research_agent\.(?:application|jobs)|chemical_runtime|research_compute)\b", text):
            errors.append(f"research_agent.research imports an execution namespace: {path.relative_to(ROOT)}")
    for namespace in ("artifacts", "foundation"):
        for path in _python_files(ROOT / "backend/src/research_agent" / namespace):
            if re.search(r"(?:from|import)\s+(?:research_agent\.research|research_agent\.application)\b", path.read_text()):
                errors.append(f"storage/foundation imports research policy: {path.relative_to(ROOT)}")
    for relative in RETIRED_RUNTIME_PATHS:
        path = ROOT / relative
        if path.is_file() or (path.is_dir() and any(
            item.is_file() and item.suffix in {".py", ".mjs", ".mts", ".cjs", ".cts", ".js", ".ts", ".jsx", ".tsx", ".json"}
            for item in path.rglob("*")
        )):
            errors.append(f"retired implementation remains: {relative}")
    for root in (ROOT / "backend/src", ROOT / "packages", ROOT / "apps", ROOT / "scripts", ROOT / "tools"):
        for path in _python_files(root):
            text = path.read_text(encoding="utf-8")
            if OLD_SUBPACKAGE.search(text):
                errors.append(f"removed research_agent.application subpackage reference: {path.relative_to(ROOT)}")
    required = (
        ROOT / "backend" / "src" / "research_agent" / "foundation" / "io.py",
        ROOT / "backend" / "src" / "research_agent" / "research" / "nodes.py",
        ROOT / "backend" / "src" / "research_agent" / "jobs" / "runtime.py",
        ROOT / "backend" / "src" / "research_agent" / "bootstrap" / "launcher.py",
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
    app_server = ROOT / "apps/agent/main.mjs"
    if "source-root" in app_server.read_text(encoding="utf-8"):
        errors.append("pi-app-server exposes a replaceable source-root option")
    for path in (ROOT / "apps/agent").rglob("*.mjs"):
        if path.relative_to(ROOT).as_posix() == "apps/agent/pi/source.mjs":
            continue
        if re.search(r"packages/(?:coding-agent|durable|ai|tui)/src/", path.read_text()):
            errors.append(f"Pi private source path outside adapter: {path.relative_to(ROOT)}")
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
