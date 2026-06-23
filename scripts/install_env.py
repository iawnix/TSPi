#!/usr/bin/env python3
"""Create or refresh the isolated Conda runtime for TSAgentSkill."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime.env import (  # noqa: E402
    MANIFEST_VERSION,
    default_env_prefix,
    env_python,
    spec_sha256,
    write_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the TSAgentSkill isolated Python environment.")
    parser.add_argument("--package-root", default=str(ROOT))
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

    prefix = default_env_prefix(package_root, args.env_root)
    python = env_python(prefix)
    conda_root = _resolve_conda_root(args.conda_root)
    conda = _resolve_conda(args.conda, conda_root)
    action = "reuse" if python.exists() and not args.force else ("update" if prefix.exists() else "create")
    payload = {
        "package_root": str(package_root),
        "environment_spec": str(spec_path),
        "spec_sha256": spec_sha256(package_root),
        "env_prefix": str(prefix),
        "python_executable": str(python),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "action": action,
        "dry_run": bool(args.dry_run),
        "with_render": bool(args.with_render),
    }

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

    manifest = {
        "schema_version": MANIFEST_VERSION,
        "package_root": str(package_root),
        "environment_spec": str(spec_path),
        "spec_sha256": payload["spec_sha256"],
        "env_prefix": str(prefix),
        "python_executable": str(python),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "render_dependencies_requested": bool(args.with_render),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = write_manifest(package_root, manifest)
    payload["manifest_path"] = str(manifest_path)
    payload["action"] = action
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


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"action: {payload['action']}")
    print(f"env_prefix: {payload['env_prefix']}")
    print(f"python: {payload['python_executable']}")


if __name__ == "__main__":
    raise SystemExit(main())
