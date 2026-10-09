from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from tspi_foundation.env import RUNTIME_PROBE_VERSION, python_payload_sha256, spec_sha256


def write_test_suite_manifest(suite_root: Path, *, version: str = "0.10.0") -> Path:
    """Write the minimal complete suite identity required by launcher tests."""

    release_id = suite_root.name
    manifest_path = suite_root / ".tspi-package-release.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "tspi-package-release/4",
                "release_id": release_id,
                "package": {"name": "@iawnix/tspi", "version": version},
                "components": {
                    "agent": {"release_id": "test-agent", "version": version},
                },
                "archive": {"filename": "test.tgz", "sha256": "0" * 64, "size_bytes": 1},
                "created_at_utc": "2026-08-27T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    from tspi_foundation.layout import paths
    layout = paths(suite_root.parent.parent).initialize()
    state_path = layout.install_state
    state_path.write_text(json.dumps({
        "schema_version": "tspi-package-install/1", "current_release_id": release_id,
        "package_root": str(suite_root), "session_guard_contract": "tspi-session-guard/1",
    }) + "\n")
    state_path.chmod(0o600)
    return manifest_path


def write_test_runtime_manifest(package_root: Path, install_root: Path) -> Path:
    """Bind a test installation to the interpreter running the test suite."""

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
    origins = {name: module_root / name / "__init__.py" for name in ("jsonschema", "packaging")}
    for origin in origins.values():
        origin.parent.mkdir(parents=True, exist_ok=True)
        origin.write_text("# test runtime module marker\n", encoding="utf-8")
    environment_spec = package_root / "environment.yml"
    package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    payload_sha256 = python_payload_sha256(package_root)
    runtime_home = install_root / "var/state/installation/python"
    runtime_home.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_home / "env.json"
    payload = {
        "schema_version": "agent-runtime/3",
        "package_root": str(package_root),
        "environment_spec": str(environment_spec),
        "environment_lock": str(package_root / "environment.lock.txt"),
        "spec_sha256": spec_sha256(package_root),
        "python_payload_sha256": payload_sha256,
        "env_prefix": str(base_prefix),
        "base_python_executable": str(base_bin / "python"),
        "kernel_env_prefix": str(kernel_prefix),
        "python_executable": str(kernel_bin / "python"),
        "runtime_probe": {
            "schema_version": RUNTIME_PROBE_VERSION,
            "ok": True,
            "python": {"version": sys.version.split()[0], "executable": str(kernel_bin / "python")},
            "distribution": {
                "name": "tspi-runtime",
                "installed": True,
                "version": package["version"],
                "root": str(kernel_prefix),
                "payload_sha256": payload_sha256,
            },
            "modules": {name: {"version": "1.0-test", "origin": str(origin)} for name, origin in origins.items()},
            "capabilities": {"json_schema_validation": True, "version_constraints": True},
        },
    }
    manifest_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    return manifest_path
