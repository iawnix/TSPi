#!/usr/bin/env python3
"""CLI for preparing and publishing the managed TSPi Python runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from ._runtime_install import RuntimeInstallError, install_runtime, plan_runtime
    from ._wheel import WheelContractError
except ImportError:
    from _runtime_install import RuntimeInstallError, install_runtime, plan_runtime
    from _wheel import WheelContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the TSPi scientific base and release-specific Python kernel."
    )
    parser.add_argument("--package-root", default=str(ROOT))
    parser.add_argument("--workspace-root", help="Workspace root that owns .agents/runtime and .agents/envs.")
    parser.add_argument("--runtime-home", help="Directory that stores the runtime manifest.")
    parser.add_argument("--manifest-path", help="Explicit runtime manifest path.")
    parser.add_argument("--env-root", help="Directory that stores shared bases and release overlays.")
    parser.add_argument("--conda", help="Path to conda or mamba executable.")
    parser.add_argument("--conda-root", help="Root directory of an existing Conda or Mamba installation.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned runtime without creating it.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh the shared base and recreate only this release's kernel overlay.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)

    options = {
        "workspace_root": args.workspace_root,
        "runtime_home": args.runtime_home,
        "manifest_path": args.manifest_path,
        "env_root": args.env_root,
        "conda": args.conda,
        "conda_root": args.conda_root,
        "force": args.force,
    }
    try:
        result = (
            plan_runtime(args.package_root, **options)
            if args.dry_run
            else install_runtime(args.package_root, **options)
        )
    except (OSError, RuntimeInstallError, WheelContractError) as exc:
        print(f"error: managed runtime installation failed: {exc}", file=sys.stderr)
        return 1

    _print(result, args.json)
    return 0


def _print(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"base_action: {payload['base_action']}")
    print(f"kernel_action: {payload['kernel_action']}")
    print(f"env_prefix: {payload['env_prefix']}")
    print(f"kernel_env_prefix: {payload['kernel_env_prefix']}")
    print(f"python: {payload['python_executable']}")


if __name__ == "__main__":
    raise SystemExit(main())
