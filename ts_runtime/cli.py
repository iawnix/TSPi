"""Runtime command-line entrypoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .env import configured_python, default_env_prefix, default_runtime_home, runtime_manifest_path


def run_in_runtime(package_root: str | Path, python_args: list[str]) -> int:
    """Exec ``python_args`` with the configured skill runtime Python."""

    if not python_args:
        raise ValueError("run requires Python arguments")
    root = Path(package_root).resolve()
    python = configured_python(root) or Path(sys.executable).resolve()
    env = dict(os.environ)
    root_text = str(root)
    existing = [item for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    if root_text not in existing:
        env["PYTHONPATH"] = os.pathsep.join([root_text, *existing]) if existing else root_text
    os.execve(str(python), [str(python), *python_args], env)
    return 0


def main(argv: list[str] | None = None, *, package_root: str | Path | None = None) -> int:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: ts_runtime run <python-args...> | resolve [--json]")
        return 0
    command, python_args = args[0], args[1:]
    if command == "resolve":
        return resolve_runtime(root, python_args)
    if command != "run":
        print(f"unknown ts_runtime command: {command}", file=sys.stderr)
        return 2
    if not python_args:
        print("usage: ts_runtime run <python-args...>", file=sys.stderr)
        return 2
    return run_in_runtime(root, python_args)


def resolve_runtime(package_root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Resolve the TSAgentSkill runtime paths.")
    parser.add_argument("--package-root", default=str(package_root))
    parser.add_argument("--workspace-root")
    parser.add_argument("--runtime-home")
    parser.add_argument("--manifest-path")
    parser.add_argument("--env-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.package_root).expanduser().resolve()
    configured = configured_python(root, args.runtime_home, args.workspace_root, args.manifest_path)
    python = configured or Path(sys.executable).resolve()
    runtime_home = (
        Path(args.runtime_home).expanduser().resolve()
        if args.runtime_home
        else default_runtime_home(root, args.workspace_root)
    )
    manifest_path = runtime_manifest_path(root, args.runtime_home, args.workspace_root, args.manifest_path)
    env_prefix = default_env_prefix(root, args.env_root, args.workspace_root)
    payload = {
        "package_root": str(root),
        "runtime_home": str(runtime_home),
        "manifest_path": str(manifest_path),
        "env_prefix": str(env_prefix),
        "python_executable": str(python),
        "configured": configured is not None,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"python: {payload['python_executable']}")
        print(f"configured: {payload['configured']}")
        print(f"manifest_path: {payload['manifest_path']}")
    return 0
