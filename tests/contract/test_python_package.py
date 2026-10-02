from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import tspi_runtime

from scripts.check_package import (
    PACKAGE_VERSION,
    validate_python_project,
    validate_version_surfaces,
)
from scripts._wheel import build_wheel, inspect_wheel, source_payload_sha256 as wheel_source_payload_sha256
from tspi_runtime.runtime.env import python_payload_sha256


ROOT = Path(__file__).resolve().parents[2]


def test_python_distribution_metadata_matches_pi_release() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    validate_python_project()
    validate_version_surfaces()
    assert project["project"]["name"] == "tspi-runtime"
    assert project["tool"]["setuptools"]["package-dir"] == {"": "packages/tspi-runtime"}
    assert tspi_runtime.__version__ == package["version"] == PACKAGE_VERSION


def test_python_payload_digest_covers_code_and_runtime_data() -> None:
    original = python_payload_sha256(ROOT)
    expected_paths = {
        "packages/tspi-runtime/tspi_runtime/__init__.py",
        "packages/tspi-runtime/tspi_runtime/compute/contracts/calculation_request.schema.json",
        "packages/tspi-runtime/tspi_runtime/path_safety.py",
        "packages/tspi-runtime/tspi_runtime/research/model.py",
        "packages/tspi-runtime/tspi_runtime/research/kernel.py",
        "packages/tspi-runtime/tspi_runtime/command_catalog.json",
        "packages/tspi-runtime/tspi_runtime/analysis/results.py",
        "packages/tspi-runtime/tspi_runtime/compute/errors.py",
        "packages/tspi-runtime/tspi_runtime/platforms/config.py",
        "packages/tspi-runtime/tspi_runtime/workspace/artifacts.py",
        "packages/tspi-runtime/tspi_runtime/workspace/candidates.py",
        "packages/tspi-runtime/tspi_runtime/workspace/contracts/finding_candidates.schema.json",
        "packages/tspi-runtime/tspi_runtime/workspace/contracts/workspace.schema.json",
        "packages/tspi-runtime/tspi_runtime/workspace/operational.py",
        "packages/tspi-runtime/tspi_runtime/workspace/operation_registry.py",
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
                "import importlib.metadata,json; from pathlib import Path; import tspi_runtime; "
                "from tspi_runtime.analysis.engine import Inputs,evaluate; "
                "reaction=evaluate('reaction.parse',Inputs({},{}),{'reaction_smiles':'CCl.[OH-]>>CO.[Cl-]','multiplicities':{'reactants':[1,1],'products':[1,1]}}); "
                "root=Path(tspi_runtime.__file__).resolve().parent; "
                "print(json.dumps({'version': importlib.metadata.version('tspi-runtime'), "
                "'schema': (root/'compute/contracts/calculation_request.schema.json').is_file(), "
                "'candidate_schema': (root/'workspace/contracts/finding_candidates.schema.json').is_file(), "
                "'candidate_module': (root/'workspace/candidates.py').is_file(), "
                "'analysis_candidates': (root/'workspace/analysis_candidates.py').is_file(), "
                "'reaction_mapping': (root/'reaction/mapping.py').is_file(), "
                "'analysis_catalog': (root/'compute/analysis.py').is_file(), "
                "'scientific_analysis': reaction['verdict'], "
                "'research_state': (root/'research/kernel.py').is_file(), "
                "'web': (root/'web/static/app.js').is_file()}))"
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
        "schema": True,
        "candidate_schema": True,
        "candidate_module": True,
        "analysis_candidates": True,
        "reaction_mapping": True,
        "analysis_catalog": True,
        "scientific_analysis": "valid",
        "research_state": True,
        "web": False,
    }
