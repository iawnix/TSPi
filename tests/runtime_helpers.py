from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from ts_agent.runtime.env import python_payload_sha256


def write_test_runtime_manifest(package_root: Path, install_root: Path) -> Path:
    """Bind a test installation to the interpreter running the test suite."""

    import numpy
    import rdkit

    executable = Path(sys.executable).resolve()
    numpy_origin = Path(numpy.__file__).resolve()
    rdkit_origin = Path(rdkit.__file__).resolve()
    # Launcher tests exercise installation/runtime wiring, while
    # test_runtime_env.py owns the stricter environment-isolation cases.
    prefix = Path(os.path.commonpath((executable, numpy_origin, rdkit_origin)))
    environment_spec = package_root / "environment.yml"
    package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    payload_sha256 = python_payload_sha256(package_root)
    runtime_home = install_root / ".agents" / "runtime" / "transition-state-workflow"
    runtime_home.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_home / "env.json"
    payload = {
        "schema_version": "ts-agent-runtime/1",
        "package_root": str(package_root),
        "environment_spec": str(environment_spec),
        "spec_sha256": hashlib.sha256(environment_spec.read_bytes()).hexdigest(),
        "python_payload_sha256": payload_sha256,
        "env_prefix": str(prefix),
        "python_executable": str(executable),
        "runtime_probe": {
            "schema_version": "ts-runtime-probe/2",
            "ok": True,
            "python": {"version": sys.version.split()[0], "executable": str(executable)},
            "distribution": {
                "name": "ts-agent-kernel",
                "installed": True,
                "version": package["version"],
                "root": str(prefix),
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
