#!/usr/bin/env python3
"""Validate the Pi package manifest and npm tarball boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "@iawnix/ts-agent"
PACKAGE_VERSION = "0.11.0"
SKILL_ENTRY = "./skills/transition-state-workflow"
THEME_ENTRIES = ["./themes/ts-theme.json"]
EXTENSION_ENTRIES = [
    "./extensions/ts-workflow-control",
    "./extensions/ts-workflow-ui/index.ts",
    "./extensions/ts-workflow-review/index.ts",
    "./extensions/ts-workflow-compute/index.ts",
    "./extensions/ts-workflow-artifacts/index.ts",
]
PACKAGE_FILES = [
    "TSPi",
    "README.md",
    "pyproject.toml",
    "docs/*.md",
    "docs/adr/*.md",
    "environment.yml",
    "extensions/shared/*.ts",
    "extensions/ts-phone-bridge/*.ts",
    "extensions/ts-workflow-artifacts/*.ts",
    "extensions/ts-workflow-compute/*.ts",
    "extensions/ts-workflow-compute/*.cjs",
    "extensions/ts-workflow-control/*.ts",
    "extensions/ts-workflow-control/*.cjs",
    "extensions/ts-workflow-review/*.ts",
    "extensions/ts-workflow-ui/*.ts",
    "scripts/install_env.py",
    "scripts/install_package.py",
    "scripts/install_release.py",
    "scripts/_bootstrap.py",
    "scripts/_suite.py",
    "scripts/_wheel.py",
    "scripts/tspi_host.py",
    "scripts/ts_backend.py",
    "scripts/ts_compute.py",
    "scripts/ts_email.py",
    "scripts/ts_render.py",
    "scripts/ts_report.py",
    "scripts/ts_runtime.py",
    "scripts/ts_web.py",
    "scripts/ts_workspace.py",
    "skills/",
    "themes/*.json",
    "src/agent-core/*.cjs",
    "src/agents/compute/*.ts",
    "src/agents/compute/*.cjs",
    "src/agents/compute/prompts/*.md",
    "src/agents/review/*.ts",
    "src/agents/review/*.cjs",
    "src/agents/review/prompts/*.md",
    "src/artifacts/*.cjs",
    "python/ts_agent/*.py",
    "python/ts_agent/backends/*.py",
    "python/ts_agent/compute/*.py",
    "python/ts_agent/compute/contracts/*.json",
    "python/ts_agent/email/*.py",
    "python/ts_agent/remote/*.py",
    "python/ts_agent/remote/*.toml",
    "python/ts_agent/render/*.py",
    "python/ts_agent/report/*.py",
    "python/ts_agent/runtime/*.py",
    "python/ts_agent/structures/*.py",
    "python/ts_agent/validation/*.py",
    "python/ts_agent/validation/predicates/*.py",
    "python/ts_agent/validation/templates/builtin/*.json",
    "python/ts_agent/validation/acceptance_profiles/*.json",
    "python/ts_agent/web/*.py",
    "python/ts_agent/web/static/*.html",
    "python/ts_agent/web/static/*.css",
    "python/ts_agent/web/static/*.js",
    "python/ts_agent/workspace/*.py",
    "python/ts_agent/workspace/contracts/*.json",
    "python-dist/*.whl",
]
REQUIRED_TARBALL_FILES = {
    "package.json",
    "pyproject.toml",
    "TSPi",
    "docs/ARCHITECTURE.md",
    "docs/INSTALLATION.md",
    "docs/MAINTAINER_GUIDE.md",
    "environment.yml",
    "scripts/install_env.py",
    "scripts/install_package.py",
    "scripts/install_release.py",
    "scripts/_bootstrap.py",
    "scripts/_suite.py",
    "scripts/_wheel.py",
    "scripts/tspi_host.py",
    "skills/transition-state-workflow/SKILL.md",
    "themes/ts-theme.json",
    "extensions/shared/tool-catalog.ts",
    "extensions/shared/subagent-status.ts",
    "extensions/shared/activity-events.ts",
    "extensions/shared/icons.ts",
    "extensions/shared/review-tool-presentation.ts",
    "extensions/ts-phone-bridge/index.ts",
    "extensions/ts-phone-bridge/bridge-client.ts",
    "extensions/ts-phone-bridge/policy.ts",
    "extensions/ts-phone-bridge/protocol.ts",
    "extensions/ts-workflow-control/index.ts",
    "extensions/ts-workflow-ui/index.ts",
    "extensions/ts-workflow-ui/activity-panel.ts",
    "extensions/ts-workflow-ui/activity-store.ts",
    "extensions/ts-workflow-review/index.ts",
    "extensions/ts-workflow-compute/index.ts",
    "extensions/ts-workflow-artifacts/index.ts",
    "src/agent-core/agent-protocol.cjs",
    "src/agent-core/fact-kinds.cjs",
    "src/agent-core/failure-taxonomy.cjs",
    "src/agent-core/activity-journal.cjs",
    "src/agent-core/provider-turn.cjs",
    "src/agents/compute/runtime.ts",
    "src/agents/compute/task-packet.cjs",
    "src/agents/compute/output-schema.cjs",
    "src/agents/compute/result-tool.ts",
    "src/agents/compute/prompts/core.md",
    "src/agents/review/runtime.ts",
    "src/agents/review/prompts/core.md",
    "src/artifacts/request-contract.cjs",
    "python/ts_agent/compute/artifacts.py",
    "python/ts_agent/email/delivery.py",
    "python/ts_agent/runtime/probe.py",
    "python/ts_agent/structures/api.py",
    "python/ts_agent/structures/seed.py",
    "python/ts_agent/workspace/engine.py",
    "python/ts_agent/workspace/context.py",
    "python/ts_agent/workspace/bootstrap.py",
    "python/ts_agent/workspace/contracts/research_phase.schema.json",
    "python/ts_agent/workspace/contracts/research_phase_registry.schema.json",
    "python/ts_agent/workspace/contracts/research_node.schema.json",
    "python/ts_agent/validation/engine.py",
    "python/ts_agent/validation/templates/builtin/classical-ts__1.json",
    "python/ts_agent/validation/acceptance_profiles/accepted-ts__3.json",
    "python/ts_agent/web/static/index.html",
    "python/ts_agent/web/static/app.css",
    "python/ts_agent/web/static/app.js",
    "python/ts_agent/web/static/attempt-timeline.js",
    "python/ts_agent/web/static/claim-map.js",
    "python/ts_agent/web/static/research-tree.js",
    "python/ts_agent/web/reloader.py",
    "docs/adr/0001-phase-node-research-kernel.md",
}
REMOVED_PREFIXES = (
    "agent-core/",
    "agent-skills/",
    "artifact-agent/",
    "compute-agent/",
    "references/",
    "review-agent/",
    "templates/",
    "ts_backends/",
    "ts_compute/",
    "ts_email/",
    "ts_remote/",
    "ts_render/",
    "ts_report/",
    "ts_runtime/",
    "ts_structures/",
    "ts_validation/",
    "ts_web/",
    "ts_workspace/",
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
FORBIDDEN_RUNTIME_FILES = {
    "scripts/build_package.py",
    "scripts/build_release.py",
    "scripts/check_package.py",
}
REQUIRED_EXECUTABLE_FILES = {"TSPi", "scripts/ts_web.py"}


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
    if manifest.get("dependencies"):
        errors.append("Pi-provided runtime packages must not be bundled as dependencies")
    peer_dependencies = manifest.get("peerDependencies")
    if not isinstance(peer_dependencies, dict) or peer_dependencies.get("typebox") != "*":
        errors.append("Pi-provided typebox must be declared as peerDependencies.typebox='*'")

    pi = manifest.get("pi")
    if not isinstance(pi, dict):
        errors.append("package pi metadata must be an object")
    else:
        if pi.get("skills") != [SKILL_ENTRY]:
            errors.append(f"pi.skills must contain only {SKILL_ENTRY}")
        if pi.get("themes") != THEME_ENTRIES:
            errors.append("pi.themes does not match the public theme inventory")
        if pi.get("extensions") != EXTENSION_ENTRIES:
            errors.append("pi.extensions does not match the public extension inventory")

    skill_path = ROOT / SKILL_ENTRY.removeprefix("./") / "SKILL.md"
    if not skill_path.is_file():
        errors.append(f"registered skill entry is missing SKILL.md: {skill_path.relative_to(ROOT)}")
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
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = project.get("project")
    setuptools = project.get("tool", {}).get("setuptools", {})
    version_source = ROOT / "python" / "ts_agent" / "_version.py"
    namespace = ROOT / "python" / "ts_agent" / "__init__.py"
    errors: list[str] = []
    if not isinstance(metadata, dict) or metadata.get("name") != "ts-agent-kernel":
        errors.append("pyproject project.name must be ts-agent-kernel")
    if not isinstance(metadata, dict) or metadata.get("dynamic") != ["version"]:
        errors.append("pyproject version must be sourced from ts_agent._version")
    if setuptools.get("package-dir") != {"": "python"}:
        errors.append("pyproject must use the python/ source root")
    if not version_source.is_file() or not namespace.is_file():
        errors.append("Python ts_agent namespace or version source is missing")
    else:
        expected = f'__version__ = "{PACKAGE_VERSION}"'
        if expected not in version_source.read_text(encoding="utf-8"):
            errors.append("Python distribution version does not match package.json")
    if errors:
        raise PackageCheckError("\n".join(errors))


def validate_runtime_entrypoints() -> None:
    invalid = [
        relative
        for relative in sorted(REQUIRED_EXECUTABLE_FILES)
        if not os.access(ROOT / relative, os.X_OK)
    ]
    if invalid:
        raise PackageCheckError(f"runtime entrypoints must be executable: {', '.join(invalid)}")


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
        if value.startswith("python-dist/"):
            forbidden.append(value)
            continue
        if value == "SKILL.md" or value.startswith(REMOVED_PREFIXES):
            forbidden.append(value)
            continue
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
