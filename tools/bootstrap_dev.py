#!/usr/bin/env python3
"""Prepare or diagnose the locked TSPi development toolchain."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_NAME = "ts-agent-skill"


def command_version(command: str, args: list[str] | None = None) -> str | None:
    executable = command if Path(command).is_file() else shutil.which(command)
    if not executable:
        return None
    result = subprocess.run([executable, *(args or ["--version"])], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")


def environment_prefix(conda: str) -> str | None:
    result = subprocess.run([conda, "env", "list", "--json"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return None
    try:
        environments = json.loads(result.stdout).get("envs", [])
    except json.JSONDecodeError:
        return None
    for value in environments:
        if Path(value).name == ENV_NAME:
            return value
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Run npm ci and create/update the Conda environment.")
    parser.add_argument("--conda", help="Explicit conda or mamba executable.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    conda = args.conda or shutil.which("mamba") or shutil.which("conda")
    node = command_version("node")
    npm = command_version("npm")
    report: dict[str, object] = {
        "node": node,
        "npm": npm,
        "tsc": command_version(str(ROOT / "node_modules" / ".bin" / "tsc")) or command_version("tsc"),
        "python": sys.version.split()[0],
        "conda": conda,
        "environment_name": ENV_NAME,
        "environment_prefix": environment_prefix(conda) if conda else None,
        "package_root": str(ROOT),
    }
    try:
        if args.install:
            if not shutil.which("npm"):
                raise RuntimeError("npm is required for --install")
            run(["npm", "ci"])
            if not conda:
                raise RuntimeError("conda or mamba is required for --install")
            # The environment file pins channels to conda-forge/nodefaults.
            run([conda, "env", "update", "--name", ENV_NAME, "--file", str(ROOT / "environment.yml"), "--prune"])
            report["tsc"] = command_version("node_modules/.bin/tsc") or command_version("tsc")
            report["environment_prefix"] = environment_prefix(conda)
        report["ok"] = bool(report["node"] and report["npm"] and report["conda"] and report["environment_prefix"])
    except (OSError, RuntimeError) as error:
        report["ok"] = False
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key in ("node", "npm", "tsc", "python", "conda", "environment_prefix"):
            print(f"{key}: {report.get(key) or 'missing'}")
        if report.get("error"):
            print(f"error: {report['error']}", file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
