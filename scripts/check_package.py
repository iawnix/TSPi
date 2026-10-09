#!/usr/bin/env python3
"""Validate the Pi package manifest and npm tarball boundary."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

try:
    from .package_inventory import (
        PACKAGE_FILES,
        REQUIRED_TARBALL_FILES,
        SKILL_ENTRIES,
        SKILL_ENTRY_FILES,
        RETIRED_RUNTIME_PATHS, release_files,
    )
except ImportError:
    from package_inventory import PACKAGE_FILES, REQUIRED_TARBALL_FILES, SKILL_ENTRIES, SKILL_ENTRY_FILES, RETIRED_RUNTIME_PATHS, release_files


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "@iawnix/research-agent"
PACKAGE_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
PROJECT_LICENSE = "Apache-2.0"
THEME_ENTRIES = ["./apps/agent/terminal/themes/research-agent.json"]
EXTENSION_ENTRIES: list[str] = []
REMOVED_PREFIXES = (
    "agent-core/",
    "agent-skills/",
    "artifact-agent/",
    "compute-agent/",
    "references/",
    "review-agent/",
    "templates/",
    "ts_backends/",
    "compute/",
    "notify/",
    "ts_remote/",
    "render/",
    "report/",
    "ts_runtime/",
    "ts_structures/",
    "ts_validation/",
    "ts_web/",
    "workspace/",
)
FORBIDDEN_PARTS = {
    "local_debug",
    ".agents",
    ".git",
    ".npm-cache",
    ".pytest_cache",
    ".runtime",
    "__pycache__",
    "node_modules",
    "tests",
}
FORBIDDEN_BASENAMES = {".env", "auth.json", "auth.toml", "config.toml", "models.json"}
FORBIDDEN_RUNTIME_FILES = {
    "scripts/_source_capture.py",
    "scripts/build_package.py",
    "scripts/build_release.py",
    "scripts/check_package.py",
    "scripts/test_source.py",
}
REQUIRED_EXECUTABLE_FILES = {"research-agent", "libexec/research-agent-host", "apps/agent-cli/research_web_bridge.py"}


class PackageCheckError(RuntimeError):
    pass


def load_manifest() -> dict[str, Any]:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> None:
    errors: list[str] = []
    if manifest.get("name") != PACKAGE_NAME:
        errors.append(f"package name must be {PACKAGE_NAME}")
    if manifest.get("version") != PACKAGE_VERSION:
        errors.append(f"package version must be {PACKAGE_VERSION}")
    if manifest.get("license") != PROJECT_LICENSE:
        errors.append(f"package license must be {PROJECT_LICENSE}")
    if not isinstance(manifest.get("version"), str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-rc\.(?:0|[1-9][0-9]*))?", manifest["version"]
    ):
        errors.append("package version must be a stable or rc SemVer release")
    if manifest.get("private") is not True:
        errors.append("package must remain private until release is explicitly authorized")
    if manifest.get("files") != PACKAGE_FILES:
        errors.append("package files allowlist does not match the maintained runtime boundary")
    if manifest.get("dependencies"):
        errors.append("Pi-provided runtime packages must not be bundled as dependencies")
    peer_dependencies = manifest.get("peerDependencies")
    pi_peers = {
        "@earendil-works/pi-agent-core",
        "@earendil-works/pi-ai",
        "@earendil-works/pi-coding-agent",
        "@earendil-works/pi-durable",
        "@earendil-works/pi-tui",
        "typebox",
    }
    if not isinstance(peer_dependencies, dict) or {
        name for name in pi_peers if peer_dependencies.get(name) != "*"
    }:
        errors.append("Pi-provided runtime packages must all use '*' peer dependency ranges")

    pi = manifest.get("pi")
    if not isinstance(pi, dict):
        errors.append("package pi metadata must be an object")
    else:
        if pi.get("skills") != SKILL_ENTRIES:
            errors.append("pi.skills does not match the maintained Skill inventory")
        if pi.get("themes") != THEME_ENTRIES:
            errors.append("pi.themes does not match the public theme inventory")
        if pi.get("extensions") != EXTENSION_ENTRIES:
            errors.append("pi.extensions does not match the public extension inventory")

    for skill_entry in SKILL_ENTRIES:
        skill_path = ROOT / skill_entry.removeprefix("./")
        if not skill_path.is_dir() or not any(skill_path.rglob("SKILL.md")):
            errors.append(f"registered skill entry is missing SKILL.md: {skill_path.relative_to(ROOT)}")
    for skill_file in SKILL_ENTRY_FILES:
        if not (ROOT / skill_file).is_file():
            errors.append(f"required Skill file is missing: {skill_file}")
    for entry in THEME_ENTRIES:
        path = ROOT / entry.removeprefix("./")
        if not path.is_file():
            errors.append(f"registered theme entry is missing: {path.relative_to(ROOT)}")
    for entry in EXTENSION_ENTRIES:
        path = ROOT / entry.removeprefix("./")
        expected = path / "index.ts" if path.is_dir() else path
        if not expected.is_file():
            errors.append(f"registered extension entry is missing: {expected.relative_to(ROOT)}")

    if errors:
        raise PackageCheckError("\n".join(errors))


def validate_python_project() -> None:
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    metadata = project["project"]
    setuptools = project["tool"]["setuptools"]
    if metadata["name"] != "research-agent" or metadata["license"] != PROJECT_LICENSE:
        raise PackageCheckError("Python distribution identity does not match the product")
    if metadata.get("dynamic") != ["version"] or setuptools["dynamic"]["version"] != {"attr": "research_agent._version.__version__"}:
        raise PackageCheckError("Python version must come from the generated product version")
    if setuptools.get("package-dir") != {"": "src"} or setuptools["packages"]["find"] != {"where": ["src"], "include": ["research_agent", "research_agent.*"]}:
        raise PackageCheckError("Python distribution must use the single backend/src namespace")
    if not (ROOT / "backend/src/research_agent/__init__.py").is_file():
        raise PackageCheckError("Python namespace is missing")


def validate_version_surfaces() -> None:
    # This build check uses the same generator as release preparation.
    sys.path.insert(0, str(ROOT))
    from tools.version import check
    try:
        check(ROOT)
    except ValueError as error:
        raise PackageCheckError(str(error)) from error


def validate_runtime_entrypoints() -> None:
    invalid = [
        relative
        for relative in sorted(REQUIRED_EXECUTABLE_FILES)
        if not os.access(ROOT / relative, os.X_OK)
    ]
    if invalid:
        raise PackageCheckError(f"runtime entrypoints must be executable: {', '.join(invalid)}")


def npm_pack_files() -> set[str]:
    with tempfile.TemporaryDirectory(prefix="research-agent-npm-cache-") as cache:
        env = dict(os.environ)
        env["npm_config_cache"] = cache
        completed = subprocess.run(
            ["npm", "pack", "--dry-run", "--json"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "npm pack failed"
        raise PackageCheckError(detail)
    try:
        payload = json.loads(completed.stdout)
        files = payload[0]["files"]
        return {str(item["path"]) for item in files}
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise PackageCheckError(f"could not parse npm pack JSON: {error}") from error


def expanded_allowlisted_files() -> set[str]:
    return release_files(ROOT)


def validate_tarball(files: set[str]) -> None:
    errors: list[str] = []
    missing = sorted(REQUIRED_TARBALL_FILES - files)
    if missing:
        errors.append(f"required runtime files are missing: {', '.join(missing)}")

    allowlisted = {"package.json", *expanded_allowlisted_files()}
    omitted = sorted(allowlisted - files)
    unexpected = sorted(files - allowlisted)
    if omitted:
        errors.append(f"allowlisted files are missing from the tarball: {', '.join(omitted)}")
    if unexpected:
        errors.append(f"tarball contains files outside the allowlist: {', '.join(unexpected)}")

    forbidden: list[str] = []
    for value in sorted(files):
        path = Path(value)
        if value.startswith("python-dist/"):
            forbidden.append(value)
            continue
        if value == "SKILL.md" or value.startswith(REMOVED_PREFIXES):
            forbidden.append(value)
            continue
        if any(value.startswith(path) if path.endswith("/") else value == path for path in RETIRED_RUNTIME_PATHS):
            errors.append(f"retired implementation included in package: {value}")
        if value in FORBIDDEN_RUNTIME_FILES:
            forbidden.append(value)
            continue
        if FORBIDDEN_PARTS.intersection(path.parts):
            forbidden.append(value)
            continue
        if path.name in FORBIDDEN_BASENAMES or path.suffix in {".pyc", ".pyo"}:
            forbidden.append(value)
    if forbidden:
        errors.append(f"forbidden files are present in the tarball: {', '.join(forbidden)}")

    if errors:
        raise PackageCheckError("\n".join(errors))


def main() -> int:
    try:
        validate_manifest(load_manifest())
        validate_python_project()
        validate_version_surfaces()
        validate_runtime_entrypoints()
        files = npm_pack_files()
        validate_tarball(files)
    except (OSError, PackageCheckError, json.JSONDecodeError) as error:
        print(f"package check failed: {error}", file=sys.stderr)
        return 1
    print(f"package check passed: {PACKAGE_NAME}@{PACKAGE_VERSION}, {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
