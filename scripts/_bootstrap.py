"""Bootstrap the packaged Python kernel without importing it from source first."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType


def register_first_party_providers(package_root: str | Path) -> None:
    """Register extension implementations after the generic packages load.

    Provider registration belongs to the application/bootstrap boundary.  The
    research-compute package itself never imports a domain extension.
    """
    root = Path(package_root).expanduser().resolve()
    source = root / "extensions" / "chemical" / "providers" / "chemical_compute_provider.py"
    if not source.is_file():
        return
    name = f"_tspi_chemical_compute_{hashlib.sha256(str(source).encode()).hexdigest()[:12]}"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, source)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load compute provider: {source}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    from research_compute.provider import register_compute_provider
    register_compute_provider(module.chemical_compute_provider, replace=True)
    from research_compute.capabilities import CAPABILITY_DESCRIPTORS, register_capability
    for descriptor in CAPABILITY_DESCRIPTORS:
        if descriptor.backend in module.chemical_compute_provider.backends:
            register_capability(descriptor, provider_id="chemical", provider=module.chemical_compute_provider, replace=True)
    from research_compute.analysis import register_analysis_provider
    register_analysis_provider(module.chemical_compute_provider, provider_id="chemical", replace=True)


def load_runtime_environment(package_root: str | Path) -> ModuleType:
    root = Path(package_root).expanduser().resolve()
    source = root / "packages" / "tspi-foundation" / "tspi_foundation" / "env.py"
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
    for source_root in runtime.source_python_paths(root):
        value = str(source_root)
        if value not in sys.path:
            sys.path.insert(0, value)
    register_first_party_providers(root)
    return runtime


def activate_source_package(package_root: str | Path) -> None:
    """Expose the authored package only for installer and runtime-control code."""

    root = Path(package_root).expanduser().resolve()
    runtime = load_runtime_environment(root)
    for source_root in runtime.source_python_paths(root):
        value = str(source_root)
        if value not in sys.path: sys.path.insert(0, value)
