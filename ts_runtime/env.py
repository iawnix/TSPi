"""Conda runtime discovery for TSAgentSkill.

The skill can be installed as source code in one location while its Python
environment lives in a workspace-local environment store. Public scripts call
``ensure_runtime_python`` before importing heavier workflow modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ENV_OVERRIDE = "TS_AGENT_PYTHON"
DISABLE_REEXEC = "TS_AGENT_DISABLE_RUNTIME_REEXEC"
ENV_ROOT_OVERRIDE = "TS_AGENT_ENV_ROOT"
MANIFEST_VERSION = "ts-agent-runtime-v1"
SKILL_NAME = "transition-state-workflow"


def package_root_from_file(path: str | Path) -> Path:
    """Return the package root for a file under this skill tree."""

    current = Path(path).resolve()
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        if (parent / "SKILL.md").exists() and (parent / "scripts").exists():
            return parent
    return Path(__file__).resolve().parents[1]


def environment_spec_path(package_root: str | Path | None = None) -> Path:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    return root / "environment.yml"


def spec_sha256(package_root: str | Path | None = None) -> str:
    spec = environment_spec_path(package_root)
    return hashlib.sha256(spec.read_bytes()).hexdigest()


def runtime_manifest_path(package_root: str | Path | None = None) -> Path:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    return root / ".runtime" / "env.json"


def default_env_store(package_root: str | Path | None = None) -> Path:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    override = os.environ.get(ENV_ROOT_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()

    parts = root.parts
    if ".agents" in parts:
        index = parts.index(".agents")
        agents_root = Path(*parts[: index + 1])
        if os.access(agents_root, os.W_OK):
            return agents_root / "envs" / SKILL_NAME
        return agents_root.parent / ".envs" / SKILL_NAME

    ts_root = Path("/home/iaw/TS")
    if ts_root.exists():
        agents_root = ts_root / ".agents"
        if agents_root.exists() and os.access(agents_root, os.W_OK):
            return agents_root / "envs" / SKILL_NAME
        return ts_root / ".envs" / SKILL_NAME

    return root.parent / ".envs" / SKILL_NAME


def default_env_prefix(package_root: str | Path | None = None, env_root: str | Path | None = None) -> Path:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    store = Path(env_root).expanduser().resolve() if env_root else default_env_store(root)
    return store / spec_sha256(root)[:12]


def env_python(env_prefix: str | Path) -> Path:
    return Path(env_prefix).expanduser().resolve() / "bin" / "python"


def load_manifest(package_root: str | Path | None = None) -> dict[str, Any] | None:
    path = runtime_manifest_path(package_root)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_VERSION:
        return None
    return data


def write_manifest(package_root: str | Path, manifest: dict[str, Any]) -> Path:
    path = runtime_manifest_path(package_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def configured_python(package_root: str | Path | None = None) -> Path | None:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()

    manifest = load_manifest(package_root)
    if not manifest:
        return None
    python = manifest.get("python_executable")
    if not python:
        return None
    path = Path(str(python)).expanduser().resolve()
    return path if path.exists() else None


def ensure_runtime_python(package_root: str | Path | None = None) -> None:
    """Re-exec the current script with the configured runtime Python if needed."""

    if os.environ.get(DISABLE_REEXEC) == "1":
        return

    python = configured_python(package_root)
    if python is None:
        return

    current = Path(sys.executable).resolve()
    if current == python:
        return

    os.execv(str(python), [str(python), *sys.argv])
