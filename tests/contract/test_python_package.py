from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import research_agent

from scripts.check_package import (
    PACKAGE_VERSION,
    validate_python_project,
    validate_version_surfaces,
)
from scripts._wheel import build_wheel, inspect_wheel, source_payload_sha256 as wheel_source_payload_sha256
from research_agent.foundation.env import python_payload_sha256


ROOT = Path(__file__).resolve().parents[2]


def test_python_distribution_metadata_matches_pi_release() -> None:
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    validate_python_project()
    validate_version_surfaces()
    assert project["project"]["name"] == "research-agent"
    assert project["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert research_agent.__version__ == package["version"] == PACKAGE_VERSION


def test_python_payload_digest_covers_code_and_runtime_data() -> None:
    original = python_payload_sha256(ROOT)
    expected_paths = {
        "backend/src/research_agent/application/__init__.py",
        "backend/src/research_agent/application/execution.py",
        "backend/src/research_agent/foundation/path_safety.py",
        "backend/src/research_agent/application/command_catalog.json",
        "backend/src/research_agent/artifacts/__init__.py",
        "backend/src/research_agent/jobs/runtime.py",
        "backend/src/research_agent/research/nodes.py",
        "backend/src/research_agent/foundation/protocol.json",
        "backend/src/research_agent/research/operational_ids.py",
        "backend/src/research_agent/artifacts/registry.py",
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
    assert descriptor["name"] == "research-agent"
    assert descriptor["version"] == PACKAGE_VERSION
    assert descriptor["payload_sha256"] == python_payload_sha256(ROOT)
    assert repeated == descriptor
    assert sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*.egg-info")) == before
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert not any(name.startswith(("research_compute/", "research_agent_provider_runtime/")) for name in names)
    assert not {"research_agent.research/model.py", "research_agent.research/decisions.py", "research_agent.research/evidence.py"} & names


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
                "import importlib.metadata,json; from pathlib import Path; import research_agent.application,research_agent.research; "
                "root=Path(research_agent.application.__file__).resolve().parent; state=Path(research_agent.research.__file__).resolve().parent; "
                "from research_agent.research.operational_ids import allocate_operational_id; "
                "print(json.dumps({'version': importlib.metadata.version('research-agent'), "
                "'operations_schema': (state/'nodes.py').is_file(), "
                "'retired_model_export': hasattr(research_agent.research, 'ResearchMap'), "
                "'research_agent.research': (state/'nodes.py').is_file(), "
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
        "research_agent.research": True,
        "web": False,
    }
