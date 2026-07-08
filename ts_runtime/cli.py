"""Runtime command-line entrypoints."""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(prog="ts_runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run Python arguments under the configured skill runtime.")
    run.add_argument("python_args", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command == "run":
        if not args.python_args:
            parser.error("run requires Python arguments, for example: ts_runtime run -m pytest -q")
        return run_in_runtime(root, args.python_args)
    raise AssertionError(args.command)
