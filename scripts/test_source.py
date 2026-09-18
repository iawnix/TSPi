#!/usr/bin/env python3
"""Run source validation through a temporary, wheel-backed managed runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from _bootstrap import load_runtime_environment
from _wheel import WheelContractError, build_wheel
from _runtime_install import (
    RuntimeInstallError,
    _base_action,
    _clean_python_environment,
    _pip_install_wheel,
    _prepare_base,
    _resolve_conda,
    _resolve_conda_root,
    _run_runtime_probe,
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.test.manifest import suite_paths

RESULT_SCHEMA_VERSION = "ts-source-test/1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the current ts-agent-kernel wheel and test it in a temporary overlay."
    )
    parser.add_argument("--package-root", default=str(ROOT))
    parser.add_argument("--env-root", help="Directory containing the shared scientific base.")
    parser.add_argument("--base-prefix", help="Explicit healthy scientific base to reuse.")
    parser.add_argument("--conda", help="Path to conda or mamba executable.")
    parser.add_argument("--conda-root", help="Root directory of an existing Conda or Mamba installation.")
    parser.add_argument("--force-base", action="store_true", help="Refresh the selected scientific base first.")
    parser.add_argument("--result-path", help="Path for the machine-readable test record.")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    package_root = Path(args.package_root).expanduser().resolve()
    runtime = load_runtime_environment(package_root)
    env_store = (
        Path(args.env_root).expanduser().resolve()
        if args.env_root
        else runtime.default_env_store(package_root)
    )
    base_prefix = (
        Path(args.base_prefix).expanduser().resolve()
        if args.base_prefix
        else runtime.default_env_prefix(package_root, env_store)
    )
    base_python = runtime.env_python(base_prefix)
    result_path = (
        Path(args.result_path).expanduser().resolve()
        if args.result_path
        else package_root
        / ".runtime"
        / "test-results"
        / f"source-test-{runtime.python_payload_sha256(package_root)[:16]}.json"
    )
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    if not pytest_args:
        pytest_args = ["-q", *suite_paths("source")]

    record: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": False,
        "package_root": str(package_root),
        "environment_spec": str(package_root / "environment.yml"),
        "runtime_requirements": str(package_root / "requirements-runtime.txt"),
        "spec_sha256": runtime.spec_sha256(package_root),
        "python_payload_sha256": runtime.python_payload_sha256(package_root),
        "base_env_prefix": str(base_prefix),
        "base_python_executable": str(base_python),
        "pytest": {"args": pytest_args, "returncode": None},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        conda_root = _resolve_conda_root(args.conda_root)
        conda = _resolve_conda(args.conda, conda_root)
        base_action = _base_action(base_prefix, base_python, args.force_base)
        if base_action != "reuse" and conda is None:
            raise RuntimeInstallError(
                "the scientific base is unavailable and conda or mamba could not be resolved"
            )
        base_action = _prepare_base(
            conda,
            base_prefix,
            base_python,
            package_root / "environment.yml",
            package_root / "requirements-runtime.txt",
            package_root,
            base_action,
        )
        record["base_action"] = base_action
        record["conda_executable"] = conda

        with tempfile.TemporaryDirectory(prefix="ts-agent-source-test-") as temporary:
            temporary_root = Path(temporary)
            wheel_dir = temporary_root / "wheel"
            overlay = temporary_root / "kernel"
            descriptor = build_wheel(package_root, wheel_dir, python=base_python)
            wheel = wheel_dir / descriptor["filename"]
            _create_test_overlay(base_python, overlay)
            overlay_python = overlay / "bin" / "python"
            installed = _pip_install_wheel(overlay_python, wheel, package_root)
            if installed.returncode != 0:
                raise RuntimeInstallError("failed to install the source wheel into the test overlay")
            probe = _run_runtime_probe(overlay_python, package_root)
            _validate_test_layout(probe, base_prefix, overlay)
            record["python_executable"] = str(overlay_python)
            record["python_wheel"] = descriptor
            record["runtime_probe"] = probe

            environment = _clean_python_environment()
            environment["TS_PACKAGE_ROOT"] = str(package_root)
            environment["PATH"] = os.pathsep.join(
                [str(overlay / "bin"), str(base_prefix / "bin"), environment.get("PATH", "")]
            )
            environment.pop("PYTEST_ADDOPTS", None)
            environment.pop("PYTEST_PLUGINS", None)
            command = [
                str(overlay_python),
                "-m",
                "pytest",
                "--override-ini",
                "pythonpath=.",
                *pytest_args,
            ]
            completed = subprocess.run(
                command,
                cwd=package_root,
                env=environment,
                text=True,
                check=False,
            )
            record["pytest"]["returncode"] = completed.returncode
            record["ok"] = completed.returncode == 0
    except (OSError, RuntimeInstallError, WheelContractError) as exc:
        record["error"] = {"class": type(exc).__name__, "message": str(exc)}
        returncode = 1
    else:
        returncode = int(record["pytest"]["returncode"] or 0)

    _write_record(result_path, record)
    print(f"managed source test record: {result_path}")
    if not record["ok"] and "error" in record:
        print(f"managed source test failed: {record['error']['message']}", file=sys.stderr)
    return returncode


def _create_test_overlay(base_python: Path, prefix: Path) -> None:
    completed = subprocess.run(
        [
            str(base_python),
            "-m",
            "venv",
            "--copies",
            "--system-site-packages",
            str(prefix),
        ],
        text=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeInstallError(
            f"temporary kernel overlay creation failed with exit code {completed.returncode}"
        )


def _validate_test_layout(probe: dict[str, Any], base_prefix: Path, overlay: Path) -> None:
    modules = probe.get("modules")
    distribution = probe.get("distribution")
    python = probe.get("python")
    if not isinstance(modules, dict) or not isinstance(distribution, dict) or not isinstance(python, dict):
        raise RuntimeInstallError("test runtime probe has an invalid layout")
    for name in ("numpy", "rdkit"):
        module = modules.get(name)
        origin = module.get("origin") if isinstance(module, dict) else None
        if not isinstance(origin, str) or not Path(origin).resolve().is_relative_to(base_prefix):
            raise RuntimeInstallError(f"{name} did not load from the scientific base")
    distribution_root = distribution.get("root")
    executable = python.get("executable")
    if not isinstance(distribution_root, str) or not Path(distribution_root).resolve().is_relative_to(overlay):
        raise RuntimeInstallError("ts-agent-kernel did not load from the temporary overlay")
    if not isinstance(executable, str) or not Path(executable).resolve().is_relative_to(overlay):
        raise RuntimeInstallError("pytest interpreter did not load from the temporary overlay")


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
