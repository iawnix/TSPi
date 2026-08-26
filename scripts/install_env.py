#!/usr/bin/env python3
"""Create or refresh the isolated Conda runtime for TSAgentSkill."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import load_runtime_environment
from _wheel import WheelContractError, build_wheel, release_wheel

runtime_environment = load_runtime_environment(ROOT)
MANIFEST_VERSION = runtime_environment.MANIFEST_VERSION
default_env_prefix = runtime_environment.default_env_prefix
default_runtime_home = runtime_environment.default_runtime_home
env_python = runtime_environment.env_python
python_payload_sha256 = runtime_environment.python_payload_sha256
runtime_manifest_path = runtime_environment.runtime_manifest_path
spec_sha256 = runtime_environment.spec_sha256
write_manifest = runtime_environment.write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the TSAgentSkill isolated Python environment.")
    parser.add_argument("--package-root", default=str(ROOT))
    parser.add_argument("--workspace-root", help="Workspace root that owns .agents/runtime and .agents/envs.")
    parser.add_argument("--runtime-home", help="Directory that stores the runtime manifest.")
    parser.add_argument("--manifest-path", help="Explicit runtime manifest path.")
    parser.add_argument("--env-root", help="Directory that stores hashed Conda prefixes.")
    parser.add_argument("--conda", help="Path to conda or mamba executable.")
    parser.add_argument("--conda-root", help="Root directory of an existing Conda or Mamba installation.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned environment without creating it.")
    parser.add_argument("--force", action="store_true", help="Run conda env update even when the prefix already exists.")
    parser.add_argument("--with-render", action="store_true", help="Also install optional xyzrender into the runtime env.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    package_root = Path(args.package_root).expanduser().resolve()
    spec_path = package_root / "environment.yml"
    if not spec_path.exists():
        print(f"error: missing environment spec: {spec_path}", file=sys.stderr)
        return 2

    prefix = default_env_prefix(package_root, args.env_root, args.workspace_root)
    python = env_python(prefix)
    runtime_home = (
        Path(args.runtime_home).expanduser().resolve()
        if args.runtime_home
        else default_runtime_home(package_root, args.workspace_root)
    )
    manifest_path = runtime_manifest_path(
        package_root,
        runtime_home=args.runtime_home,
        workspace_root=args.workspace_root,
        manifest_path=args.manifest_path,
    )
    conda_root = _resolve_conda_root(args.conda_root)
    conda = _resolve_conda(args.conda, conda_root)
    action = "reuse" if python.exists() and not args.force else ("update" if prefix.exists() else "create")
    try:
        bundled_distribution = release_wheel(package_root)
    except WheelContractError as exc:
        print(f"error: Python distribution contract failed: {exc}", file=sys.stderr)
        return 1
    payload = {
        "package_root": str(package_root),
        "environment_spec": str(spec_path),
        "spec_sha256": spec_sha256(package_root),
        "python_distribution": runtime_environment.PYTHON_DISTRIBUTION,
        "python_payload_sha256": python_payload_sha256(package_root),
        "python_install_source": (
            "bundled-release-wheel" if bundled_distribution else "source-wheel-build"
        ),
        "env_prefix": str(prefix),
        "runtime_home": str(runtime_home),
        "manifest_path": str(manifest_path),
        "python_executable": str(python),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "action": action,
        "dry_run": bool(args.dry_run),
        "with_render": bool(args.with_render),
    }
    if bundled_distribution is not None:
        payload["python_wheel"] = bundled_distribution[1]

    if args.dry_run:
        _print(payload, args.json)
        return 0

    if conda is None:
        print(
            "error: conda or mamba not found; set --conda, --conda-root, "
            "TS_AGENT_CONDA_EXE, or TS_AGENT_CONDA_ROOT",
            file=sys.stderr,
        )
        return 2

    prefix.parent.mkdir(parents=True, exist_ok=True)
    if action == "create":
        command = _conda_env_command(conda, "create", prefix, spec_path)
    elif action == "update":
        command = _conda_env_command(conda, "update", prefix, spec_path)
    else:
        command = []

    if command:
        completed = subprocess.run(command, text=True, check=False)
        if completed.returncode != 0:
            return completed.returncode

    if not python.exists():
        print(f"error: environment was created but Python is missing: {python}", file=sys.stderr)
        return 1

    if args.with_render:
        completed = subprocess.run([str(python), "-m", "pip", "install", "xyzrender>=0.2.1"], text=True, check=False)
        if completed.returncode != 0:
            return completed.returncode

    try:
        completed, distribution_install = _install_python_distribution(python, package_root)
    except WheelContractError as exc:
        print(f"error: Python distribution contract failed: {exc}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        return completed.returncode
    payload["python_wheel"] = distribution_install

    try:
        runtime_probe = _run_runtime_probe(python, package_root)
    except RuntimeError as exc:
        print(f"error: managed runtime capability probe failed: {exc}", file=sys.stderr)
        return 1

    manifest = {
        "schema_version": MANIFEST_VERSION,
        "package_root": str(package_root),
        "environment_spec": str(spec_path),
        "spec_sha256": payload["spec_sha256"],
        "python_payload_sha256": payload["python_payload_sha256"],
        "python_wheel": distribution_install,
        "env_prefix": str(prefix),
        "runtime_home": str(runtime_home),
        "manifest_path": str(manifest_path),
        "python_executable": str(python),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "render_dependencies_requested": bool(args.with_render),
        "runtime_probe": runtime_probe,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = write_manifest(
        package_root,
        manifest,
        runtime_home=args.runtime_home,
        workspace_root=args.workspace_root,
        manifest_path=args.manifest_path,
    )
    payload["manifest_path"] = str(manifest_path)
    payload["action"] = action
    payload["runtime_probe"] = runtime_probe
    _print(payload, args.json)
    return 0


def _resolve_conda_root(explicit: str | None) -> Path | None:
    root = explicit or os.environ.get("TS_AGENT_CONDA_ROOT")
    if not root:
        return None
    return Path(root).expanduser().resolve()


def _resolve_conda(explicit: str | None, conda_root: Path | None) -> str | None:
    candidates = [
        explicit,
        *_conda_root_candidates(conda_root),
        os.environ.get("TS_AGENT_CONDA_EXE"),
        *_conda_root_candidates(_resolve_conda_root(None) if conda_root is None else None),
        shutil.which("mamba"),
        shutil.which("conda"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().exists():
            return str(Path(candidate).expanduser().resolve())
    return None


def _conda_root_candidates(conda_root: Path | None) -> list[str]:
    if conda_root is None:
        return []
    return [
        str(conda_root / "bin" / "mamba"),
        str(conda_root / "condabin" / "mamba"),
        str(conda_root / "bin" / "conda"),
        str(conda_root / "condabin" / "conda"),
    ]


def _conda_env_command(conda: str, action: str, prefix: Path, spec_path: Path) -> list[str]:
    command = [conda, "env", action]
    if Path(conda).name == "conda":
        command.extend(["--solver", "libmamba"])
    command.extend(["-p", str(prefix), "-f", str(spec_path)])
    if action == "update":
        command.append("--prune")
    return command


def _run_runtime_probe(python: Path, package_root: Path) -> dict:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONHOME", None)
    completed = subprocess.run(
        [str(python), "-m", "ts_agent.runtime.probe", "--json"],
        cwd=package_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "probe process failed"
        raise RuntimeError(detail)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("probe did not return valid JSON") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("probe returned an unhealthy result")
    return result


def _install_python_distribution(
    python: Path,
    package_root: Path,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    bundled = release_wheel(package_root)
    if bundled is not None:
        wheel, descriptor = bundled
        return _pip_install_wheel(python, wheel, package_root), descriptor

    with tempfile.TemporaryDirectory(prefix="ts-agent-install-wheel-") as temporary:
        wheel_dir = Path(temporary)
        descriptor = build_wheel(package_root, wheel_dir, python=python)
        wheel = wheel_dir / descriptor["filename"]
        completed = _pip_install_wheel(python, wheel, package_root)
    return completed, {**descriptor, "source": "source-wheel-build"}


def _pip_install_wheel(
    python: Path,
    wheel: Path,
    package_root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-cache-dir",
            "--force-reinstall",
            str(wheel),
        ],
        cwd=package_root,
        text=True,
        check=False,
    )


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"action: {payload['action']}")
    print(f"env_prefix: {payload['env_prefix']}")
    print(f"python: {payload['python_executable']}")


if __name__ == "__main__":
    raise SystemExit(main())
