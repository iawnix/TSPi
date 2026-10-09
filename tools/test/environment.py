"""Test dependencies have their own lock and never use the Host base."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


TEST_IMPORTS = "import ase,jsonschema,packaging,numpy,pytest,rdkit,scipy; from PIL import Image"


def lock_path(package_root: Path) -> Path:
    return package_root / "tools/test/environment.lock.txt"


def spec_sha256(package_root: Path) -> str:
    return hashlib.sha256(lock_path(package_root).read_bytes()).hexdigest()


def default_prefix(package_root: Path, env_root: Path) -> Path:
    return env_root / "test-base" / spec_sha256(package_root)[:12]


def probe(python: Path) -> bool:
    if not python.is_file() or not os.access(python, os.X_OK):
        return False
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return subprocess.run([str(python), "-c", TEST_IMPORTS], env=environment,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False).returncode == 0
