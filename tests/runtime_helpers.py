from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from ts_agent.runtime.env import python_payload_sha256


def write_test_suite_manifest(suite_root: Path, *, version: str = "0.10.0") -> Path:
    """Write the minimal complete suite identity required by launcher tests."""

    release_id = suite_root.name
    manifest_path = suite_root / ".tspi-package-release.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "tspi-package-release/3",
                "release_id": release_id,
                "package": {"name": "@iawnix/tspi", "version": version},
                "components": {
                    "agent": {"release_id": "test-agent", "version": version},
                    "web": {},
                    "phone": {},
                },
                "archive": {"filename": "test.tgz", "sha256": "0" * 64, "size_bytes": 1},
                "created_at_utc": "2026-08-27T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state_path = suite_root.parent.parent / "install-state.json"
    state_path.write_text(json.dumps({
        "schema_version": "tspi-package-install/1", "current_release_id": release_id,
        "package_root": str(suite_root), "session_guard_contract": "tspi-session-guard/1",
    }) + "\n")
    state_path.chmod(0o600)
    return manifest_path


def write_test_runtime_manifest(package_root: Path, install_root: Path) -> Path:
    """Bind a test installation to the interpreter running the test suite."""

    import numpy
    import rdkit

    # Launcher tests exercise installation/runtime wiring, while
    # test_runtime_env.py owns the stricter environment-isolation cases.
    runtime_root = install_root / ".test-python-runtime"
    base_prefix = runtime_root / "base"
    kernel_prefix = runtime_root / "kernel"
    base_bin = base_prefix / "bin"
    kernel_bin = kernel_prefix / "bin"
    base_bin.mkdir(parents=True, exist_ok=True)
    kernel_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sys._base_executable, base_bin / "python")
    shutil.copy2(sys.executable, kernel_bin / "python")
    shutil.copy2(sys.executable, kernel_bin / "python3")
    for executable in (base_bin / "python", kernel_bin / "python", kernel_bin / "python3"):
        executable.chmod(0o755)
    module_root = base_prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    numpy_origin = module_root / "numpy" / "__init__.py"
    rdkit_origin = module_root / "rdkit" / "__init__.py"
    for origin in (numpy_origin, rdkit_origin):
        origin.parent.mkdir(parents=True, exist_ok=True)
        origin.write_text("# test runtime module marker\n", encoding="utf-8")
    environment_spec = package_root / "environment.yml"
    package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    payload_sha256 = python_payload_sha256(package_root)
    runtime_home = install_root / ".agents" / "runtime" / "tspi"
    runtime_home.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_home / "env.json"
    payload = {
        "schema_version": "ts-agent-runtime/2",
        "package_root": str(package_root),
        "environment_spec": str(environment_spec),
        "spec_sha256": hashlib.sha256(environment_spec.read_bytes()).hexdigest(),
        "python_payload_sha256": payload_sha256,
        "env_prefix": str(base_prefix),
        "base_python_executable": str(base_bin / "python"),
        "kernel_env_prefix": str(kernel_prefix),
        "python_executable": str(kernel_bin / "python"),
        "runtime_probe": {
            "schema_version": "ts-runtime-probe/2",
            "ok": True,
            "python": {"version": sys.version.split()[0], "executable": str(kernel_bin / "python")},
            "distribution": {
                "name": "ts-agent-kernel",
                "installed": True,
                "version": package["version"],
                "root": str(kernel_prefix),
                "payload_sha256": payload_sha256,
            },
            "modules": {
                "numpy": {
                    "version": numpy.__version__,
                    "origin": str(numpy_origin),
                },
                "rdkit": {
                    "version": rdkit.__version__,
                    "origin": str(rdkit_origin),
                },
            },
            "capabilities": {
                "rdkit_smiles_parse": True,
                "rdkit_etkdg_embed": True,
                "rdkit_uff_optimize": True,
            },
        },
    }
    manifest_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    return manifest_path
