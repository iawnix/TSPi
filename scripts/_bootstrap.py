"""Bootstrap the packaged Python kernel without importing it from source first."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType


def load_runtime_environment(package_root: str | Path) -> ModuleType:
    root = Path(package_root).expanduser().resolve()
    source = root / "packages" / "tspi-runtime" / "tspi_runtime" / "runtime" / "env.py"
    if not source.is_file():
        raise RuntimeError(f"TS Agent runtime bootstrap module is missing: {source}")
    name = f"_tspi_runtime_runtime_env_{hashlib.sha256(str(source).encode()).hexdigest()[:12]}"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load TS Agent runtime bootstrap module: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def bootstrap_python_package(
    package_root: str | Path,
    *,
    required: bool = False,
    workspace_from_argv: bool = False,
    entrypoint: str | Path | None = None,
    install_root: str | Path | None = None,
) -> ModuleType:
    """Select the managed interpreter, then import installed or source code."""

    root = Path(package_root).expanduser().resolve()
    runtime = load_runtime_environment(root)
    os.environ[runtime.PACKAGE_ROOT_OVERRIDE] = str(root)
    if workspace_from_argv:
        runtime.seed_workspace_root_from_argv()
    if entrypoint is not None:
        runtime.seed_installation_runtime_from_entrypoint(entrypoint)
    if install_root is not None:
        runtime.seed_installation_runtime(install_root, authoritative=True)
    python = runtime.ensure_runtime_python(root, required=required)
    source_packages = (
        ("tspi_runtime", root / "packages" / "tspi-runtime"),
        ("research_state", root / "packages" / "research-state"),
        ("research_memory", root / "packages" / "research-memory"),
        ("research_compute", root / "packages" / "research-compute"),
    )
    for package_name, source_root in source_packages:
        if importlib.util.find_spec(package_name) is None:
            value = str(source_root)
            if value not in sys.path: sys.path.insert(0, value)
    return runtime


def activate_source_package(package_root: str | Path) -> None:
    """Expose the authored package only for installer and runtime-control code."""

    root = Path(package_root).expanduser().resolve()
    for source_root in (root / "packages" / "tspi-runtime", root / "packages" / "research-state", root / "packages" / "research-memory", root / "packages" / "research-compute"):
        value = str(source_root)
        if value not in sys.path: sys.path.insert(0, value)
