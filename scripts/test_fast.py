#!/usr/bin/env python3
"""Run source tests with the current Python environment.

This entrypoint is for edit feedback. Release-backed validation remains in
``test_source.py`` and is intentionally more expensive.
"""

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

from _bootstrap import load_runtime_environment


ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA_VERSION = "ts-fast-source-test/1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.test.manifest import suite_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest directly against the authored Python source tree."
    )
    parser.add_argument("--package-root", default=str(ROOT))
    parser.add_argument("--python", help="Python interpreter with the source-test dependencies.")
    parser.add_argument(
        "--env-root",
        default=os.environ.get("TSPI_TEST_ENV_ROOT", "/home/iaw/debug/tspi-test-env"),
        help="Managed environment store containing the source-test base.",
    )
    parser.add_argument("--result-path", help="Optional path for a machine-readable test record.")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    package_root = Path(args.package_root).expanduser().resolve()
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    if not pytest_args:
        pytest_args = ["-q"]
    if not any(value.endswith(".py") for value in pytest_args):
        pytest_args.extend(suite_paths("fast"))

    python = _resolve_python(package_root, args.python, Path(args.env_root).expanduser().resolve())
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    pythonpath = [str(package_root / "packages" / "ts-agent-kernel"), str(package_root)]
    existing_pythonpath = environment.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    command = [
        str(python),
        "-m",
        "pytest",
        *pytest_args,
    ]
    record: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "mode": "fast",
        "package_root": str(package_root),
        "python_executable": str(python),
        "pytest": {"args": pytest_args, "returncode": None},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    completed = subprocess.run(command, cwd=package_root, env=environment, check=False)
    record["pytest"]["returncode"] = completed.returncode
    record["ok"] = completed.returncode == 0

    if args.result_path:
        _write_record(Path(args.result_path).expanduser().resolve(), record)
        print(f"fast source test record: {Path(args.result_path).expanduser().resolve()}")
    return completed.returncode


def _resolve_python(package_root: Path, explicit: str | None, env_root: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    else:
        runtime = load_runtime_environment(package_root)
        if env_root is not None:
            candidates.append(runtime.env_python(runtime.default_env_prefix(package_root, env_root)))
        candidates.append(Path(sys.executable).resolve())

    checked: set[Path] = set()
    for candidate in candidates:
        if candidate in checked or not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        checked.add(candidate)
        probe = subprocess.run(
            [
                str(candidate),
                "-c",
                "import ase,jsonschema,numpy,pytest,rdkit,scipy; from PIL import Image",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    detail = str(candidates[0]) if explicit else "the current Python or existing managed base"
    raise SystemExit(
        f"fast source tests require pytest in {detail}; "
        "prepare the project runtime with scripts/install_env.py or pass --python"
    )


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
