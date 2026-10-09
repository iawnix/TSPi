from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import tspi_runtime

from scripts.check_package import (
    PACKAGE_VERSION,
    validate_python_project,
    validate_version_surfaces,
)
from scripts._wheel import build_wheel, inspect_wheel, source_payload_sha256 as wheel_source_payload_sha256
from tspi_foundation.env import python_payload_sha256


ROOT = Path(__file__).resolve().parents[2]


def test_python_distribution_metadata_matches_pi_release() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    validate_python_project()
    validate_version_surfaces()
    assert project["project"]["name"] == "tspi-runtime"
    assert project["tool"]["setuptools"]["package-dir"] == {
        "tspi_runtime": "packages/tspi-runtime/tspi_runtime",
        "tspi_foundation": "packages/tspi-foundation/tspi_foundation",
        "tspi_bootstrap": "packages/tspi-bootstrap/tspi_bootstrap",
        "research_state": "packages/research-state/research_state",
        "research_memory": "packages/research-memory/research_memory",
        "artifact_store": "packages/artifact-store/artifact_store",
        "job_runtime": "packages/job-runtime/job_runtime",
    }
    assert tspi_runtime.__version__ == package["version"] == PACKAGE_VERSION


def test_python_payload_digest_covers_code_and_runtime_data() -> None:
    original = python_payload_sha256(ROOT)
    expected_paths = {
        "packages/tspi-runtime/tspi_runtime/__init__.py",
        "packages/tspi-runtime/tspi_runtime/execution.py",
        "packages/tspi-foundation/tspi_foundation/path_safety.py",
        "packages/tspi-runtime/tspi_runtime/command_catalog.json",
        "packages/artifact-store/artifact_store/__init__.py",
        "packages/job-runtime/job_runtime/runtime.py",
        "packages/research-state/research_state/contracts/operations.json",
        "packages/tspi-foundation/tspi_foundation/protocol.json",
        "packages/research-state/research_state/operational_ids.py",
        "packages/research-state/research_state/operation_registry.py",
    }

    assert all((ROOT / path).is_file() for path in expected_paths)
    assert len(original) == 64
    assert wheel_source_payload_sha256(ROOT) == original


def test_wheel_build_uses_a_temporary_source_copy(tmp_path: Path) -> None:
    before = sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*.egg-info"))

    descriptor = build_wheel(ROOT, tmp_path / "wheel")
    repeated = build_wheel(ROOT, tmp_path / "wheel-repeated")

    wheel = tmp_path / "wheel" / descriptor["filename"]
    assert descriptor == inspect_wheel(wheel)
    assert descriptor["name"] == "tspi-runtime"
    assert descriptor["version"] == PACKAGE_VERSION
    assert descriptor["payload_sha256"] == python_payload_sha256(ROOT)
    assert repeated == descriptor
    assert sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*.egg-info")) == before
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert not any(name.startswith(("research_compute/", "tspi_provider_runtime/")) for name in names)
    assert not {"research_state/model.py", "research_state/decisions.py", "research_state/evidence.py"} & names


def test_built_wheel_installs_as_a_self_contained_kernel(tmp_path: Path) -> None:
    descriptor = build_wheel(ROOT, tmp_path / "wheel")
    wheel = tmp_path / "wheel" / descriptor["filename"]
    site = tmp_path / "site"
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-cache-dir",
            "--target",
            str(site),
            str(wheel),
        ],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.metadata,json; from pathlib import Path; import tspi_runtime,research_state; "
                "root=Path(tspi_runtime.__file__).resolve().parent; state=Path(research_state.__file__).resolve().parent; "
                "from research_state.operational_ids import allocate_operational_id; "
                "print(json.dumps({'version': importlib.metadata.version('tspi-runtime'), "
                "'operations_schema': (state/'contracts/operations.json').is_file(), "
                "'retired_model_export': hasattr(research_state, 'ResearchMap'), "
                "'research_state': (state/'agent_workspace.py').is_file(), "
                "'web': False}))"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(site), "PYTHONNOUSERSITE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout) == {
        "version": PACKAGE_VERSION,
        "operations_schema": True,
        "retired_model_export": False,
        "research_state": True,
        "web": False,
    }
