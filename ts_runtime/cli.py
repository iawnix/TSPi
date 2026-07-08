"""Runtime command-line entrypoints."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .env import configured_python


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
        print("usage: ts_runtime run <python-args...>")
        return 0
    command, python_args = args[0], args[1:]
    if command != "run":
        print(f"unknown ts_runtime command: {command}", file=sys.stderr)
        return 2
    if not python_args:
        print("usage: ts_runtime run <python-args...>", file=sys.stderr)
        return 2
    return run_in_runtime(root, python_args)
