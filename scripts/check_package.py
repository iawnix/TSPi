#!/usr/bin/env python3
"""Validate the Pi package manifest and npm tarball boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "@iawnix/ts-agent"
PACKAGE_VERSION = "0.3.0"
SKILL_ENTRY = "./skills/transition-state-workflow"
EXTENSION_ENTRIES = [
    "./extensions/ts-workflow-context",
    "./extensions/ts-workflow-subagent/index.ts",
    "./extensions/ts-workflow-compute/index.ts",
    "./extensions/ts-workflow-artifacts/index.ts",
]
PACKAGE_FILES = [
    "README.md",
    "environment.yml",
    "cluster_mcp/*.py",
    "cluster_mcp/schedulers/*.py",
    "cluster_mcp/*.example.toml",
    "contracts/*.json",
    "extensions/shared/*.ts",
    "extensions/ts-workflow-artifacts/*.ts",
    "extensions/ts-workflow-compute/*.ts",
    "extensions/ts-workflow-compute/*.cjs",
    "extensions/ts-workflow-context/*.ts",
    "extensions/ts-workflow-context/*.cjs",
    "extensions/ts-workflow-subagent/*.ts",
    "scripts/*.py",
    "skills/",
    "src/agent-core/*.cjs",
    "src/agents/review/*.ts",
    "src/agents/review/*.cjs",
    "src/agents/review/prompts/*.md",
    "src/agents/compute/*.ts",
    "src/agents/compute/*.cjs",
    "src/agents/compute/*.md",
    "src/agents/compute/private-skills/*/SKILL.md",
    "src/agents/artifacts/*.ts",
    "src/agents/artifacts/*.cjs",
    "src/agents/artifacts/*.md",
    "src/agents/artifacts/private-skills/*/SKILL.md",
    "ts_backends/*.py",
    "ts_compute/*.py",
    "ts_compute/contracts/*.json",
    "ts_remote/*.py",
    "ts_render/*.py",
    "ts_report/*.py",
    "ts_runtime/*.py",
    "ts_structures/*.py",
    "ts_web/*.py",
    "ts_web/static/*.html",
    "ts_workspace/*.py",
    "ts_workspace/contracts/*.json",
    "ts_workspace/finalizers/*.py",
    "ts_workspace/readers/*.py",
    "ts_workspace/validators/*.py",
]
REQUIRED_TARBALL_FILES = {
    "package.json",
    "environment.yml",
    "scripts/install_env.py",
    "skills/transition-state-workflow/SKILL.md",
    "extensions/ts-workflow-context/index.ts",
    "extensions/ts-workflow-subagent/index.ts",
    "extensions/ts-workflow-compute/index.ts",
    "extensions/ts-workflow-artifacts/index.ts",
    "src/agent-core/agent-protocol.cjs",
    "src/agents/review/runtime.ts",
    "src/agents/compute/runtime.ts",
    "src/agents/artifacts/runtime.ts",
}
LEGACY_PREFIXES = (
    "agent-core/",
    "agent-skills/",
    "artifact-agent/",
    "compute-agent/",
    "references/",
    "review-agent/",
    "templates/",
)
FORBIDDEN_PARTS = {
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
    if manifest.get("private") is not True:
        errors.append("package must remain private until release is explicitly authorized")
    if manifest.get("files") != PACKAGE_FILES:
        errors.append("package files allowlist does not match the maintained runtime boundary")

    pi = manifest.get("pi")
    if not isinstance(pi, dict):
        errors.append("package pi metadata must be an object")
    else:
        if pi.get("skills") != [SKILL_ENTRY]:
            errors.append(f"pi.skills must contain only {SKILL_ENTRY}")
        if pi.get("extensions") != EXTENSION_ENTRIES:
            errors.append("pi.extensions does not match the public extension inventory")

    skill_path = ROOT / SKILL_ENTRY.removeprefix("./") / "SKILL.md"
    if not skill_path.is_file():
        errors.append(f"registered skill entry is missing SKILL.md: {skill_path.relative_to(ROOT)}")
    for entry in EXTENSION_ENTRIES:
        path = ROOT / entry.removeprefix("./")
        expected = path / "index.ts" if path.is_dir() else path
        if not expected.is_file():
            errors.append(f"registered extension entry is missing: {expected.relative_to(ROOT)}")

    if errors:
        raise PackageCheckError("\n".join(errors))


def npm_pack_files() -> set[str]:
    with tempfile.TemporaryDirectory(prefix="ts-agent-npm-cache-") as cache:
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
    files: set[str] = set()
    for entry in PACKAGE_FILES:
        if entry.endswith("/"):
            directory = ROOT / entry.rstrip("/")
            files.update(
                path.relative_to(ROOT).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            )
            continue
        files.update(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob(entry)
            if path.is_file()
        )
    return files


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
        if value == "SKILL.md" or value.startswith(LEGACY_PREFIXES):
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
        files = npm_pack_files()
        validate_tarball(files)
    except (OSError, PackageCheckError, json.JSONDecodeError) as error:
        print(f"package check failed: {error}", file=sys.stderr)
        return 1
    print(f"package check passed: {PACKAGE_NAME}@{PACKAGE_VERSION}, {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
