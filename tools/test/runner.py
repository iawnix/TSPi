#!/usr/bin/env python3
"""Run one named test lane from the repository test manifest."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.test.manifest import load_manifest, suite, suite_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-prefix", help="Managed scientific base for the source suite.")
    parser.add_argument("--conda-root", help="Conda root used when preparing the source suite.")
    parser.add_argument("--env-root", help="Managed environment store for the source suite.")
    parser.add_argument("--force-base", action="store_true", help="Refresh the source-suite base environment.")
    parser.add_argument("suite", choices=["list", *sorted(load_manifest()["suites"])])
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    extra = list(parsed.args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    if parsed.suite == "list":
        _print_suites()
        return 0
    selected = suite(parsed.suite)
    kind = selected["kind"]
    if kind in {"pytest-source", "pytest-managed"}:
        script_options = []
        for option, value in (("--base-prefix", parsed.base_prefix), ("--conda-root", parsed.conda_root), ("--env-root", parsed.env_root)):
            if value:
                script_options.extend([option, value])
        if parsed.force_base:
            script_options.append("--force-base")
        return _run_python_suite(parsed.suite, kind, script_options, extra)
    if kind == "node-native":
        return _run_native_pi(selected, extra)
    if kind == "package-check":
        return _run([sys.executable, str(ROOT / "scripts" / "check_package.py"), *extra])
    if kind == "scenario":
        return _run_scenario(selected, extra)
    raise SystemExit(f"suite {parsed.suite!r} is opt-in and must be run with its scenario command")


def _print_suites() -> None:
    for name, selected in sorted(load_manifest()["suites"].items()):
        print(f"{name:12} {selected['environment']:38} {selected['description']}")


def _run_python_suite(name: str, kind: str, script_options: list[str], extra: list[str]) -> int:
    script = ROOT / "scripts" / ("test_fast.py" if kind == "pytest-source" else "test_source.py")
    paths = [] if any(value.endswith((".py", ".mjs", ".cjs")) for value in extra) else suite_paths(name)
    command = [sys.executable, str(script), *script_options, "--", *paths, *extra]
    return _run(command)


def _run_native_pi(selected: dict[str, object], extra: list[str]) -> int:
    pi_source = os.environ.get("TSPI_PI_SOURCE")
    if not pi_source:
        raise SystemExit("native-pi tests require TSPI_PI_SOURCE pointing at a prepared Pi checkout")
    node = shutil.which("node")
    if not node:
        raise SystemExit("native-pi tests require Node.js")
    resolver = Path(pi_source) / "packages" / "coding-agent" / "src" / "experimental" / "source-resolver.ts"
    command = [node, "--import", str(resolver), "--test", *suite_paths("native-pi"), *extra]
    return _run(command)


def _run_scenario(selected: dict[str, object], extra: list[str]) -> int:
    paths = selected.get("paths", [])
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise SystemExit("scenario suites must declare exactly one executable path")
    scenario = ROOT / paths[0]
    if scenario.suffix == ".py":
        python = os.environ.get("TS_AGENT_PYTHON") or sys.executable
        module = ".".join(scenario.relative_to(ROOT).with_suffix("").parts)
        command = [python, "-m", module, *extra]
    elif scenario.suffix == ".mjs":
        node = shutil.which("node")
        if not node:
            raise SystemExit("Node.js is required for this scenario")
        command = [node, str(scenario), *extra]
    else:
        raise SystemExit(f"unsupported scenario file type: {scenario}")
    return _run(command)


def _run(command: list[str]) -> int:
    print("$ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
