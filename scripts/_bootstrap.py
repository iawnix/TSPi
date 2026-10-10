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
    source = root / "backend/src/research_agent/foundation/env.py"
    if not source.is_file():
        raise RuntimeError(f"CoRAgent runtime bootstrap module is missing: {source}")
    name = f"_research_agent_runtime_runtime_env_{hashlib.sha256(str(source).encode()).hexdigest()[:12]}"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, source, submodule_search_locations=[str(source.parent)])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load CoRAgent runtime bootstrap module: {source}")
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
    if (root / ".coragent-release.json").is_file() or install_root is not None:
        if python is None:
            raise runtime.RuntimeEnvironmentError("installed commands require the managed Python wheel")
        source = root / "backend/src"
        sys.path[:] = [item for item in sys.path if Path(item).resolve() != source]
        for name, module in list(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if origin and name.split(".")[0] == "research_agent" and Path(origin).resolve().is_relative_to(source):
                del sys.modules[name]
        import research_agent
        if not Path(research_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
            raise runtime.RuntimeEnvironmentError("installed commands must import the managed Python wheel")
    else:
        activate_source_package(root)
    return runtime


def activate_source_package(package_root: str | Path) -> None:
    """Expose the authored package only for installer and runtime-control code."""

    root = Path(package_root).expanduser().resolve()
    runtime = load_runtime_environment(root)
    os.environ[runtime.PACKAGE_ROOT_OVERRIDE] = str(root)
    for source_root in runtime.source_python_paths(root):
        value = str(source_root)
        if value not in sys.path: sys.path.insert(0, value)
