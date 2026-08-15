"""Conda runtime discovery for the TS Agent Pi package.

The package code and its Python environment live in separate roots. Public
scripts call ``ensure_runtime_python`` before importing heavier workflow
modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ENV_OVERRIDE = "TS_AGENT_PYTHON"
DISABLE_REEXEC = "TS_AGENT_DISABLE_RUNTIME_REEXEC"
ENV_ROOT_OVERRIDE = "TS_AGENT_ENV_ROOT"
RUNTIME_HOME_OVERRIDE = "TS_AGENT_RUNTIME_HOME"
RUNTIME_MANIFEST_OVERRIDE = "TS_AGENT_RUNTIME_MANIFEST"
WORKSPACE_ROOT_OVERRIDE = "TS_WORKSPACE_ROOT"
MANIFEST_VERSION = "ts-agent-runtime-v1"
SKILL_NAME = "transition-state-workflow"
PACKAGE_SKILL_PATH = Path("skills") / SKILL_NAME / "SKILL.md"


def package_root_from_file(path: str | Path) -> Path:
    """Return the package root for a file shipped by this Pi package."""

    current = Path(path).resolve()
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        if (
            (parent / "package.json").is_file()
            and (parent / "scripts").is_dir()
            and (parent / PACKAGE_SKILL_PATH).is_file()
        ):
            return parent
    return Path(__file__).resolve().parents[1]


def environment_spec_path(package_root: str | Path | None = None) -> Path:
    root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    return root / "environment.yml"


def spec_sha256(package_root: str | Path | None = None) -> str:
    spec = environment_spec_path(package_root)
    return hashlib.sha256(spec.read_bytes()).hexdigest()


def _resolved_package_root(package_root: str | Path | None = None) -> Path:
    return Path(package_root).expanduser().resolve() if package_root else Path(__file__).resolve().parents[1]


def _workspace_root(workspace_root: str | Path | None = None) -> Path | None:
    root = workspace_root or os.environ.get(WORKSPACE_ROOT_OVERRIDE)
    if not root:
        return None
    return Path(root).expanduser().resolve()


def default_runtime_home(
    package_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    override = os.environ.get(RUNTIME_HOME_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()

    workspace = _workspace_root(workspace_root)
    if workspace is not None:
        return workspace / ".agents" / "runtime" / SKILL_NAME

    root = _resolved_package_root(package_root)
    parts = root.parts
    if ".agents" in parts:
        index = parts.index(".agents")
        agents_root = Path(*parts[: index + 1])
        return agents_root / "runtime" / SKILL_NAME

    return root.parent / ".runtime" / SKILL_NAME


def runtime_manifest_path(
    package_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    override = manifest_path or os.environ.get(RUNTIME_MANIFEST_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()
    home = Path(runtime_home).expanduser().resolve() if runtime_home else default_runtime_home(package_root, workspace_root)
    return home / "env.json"


def default_env_store(
    package_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    override = os.environ.get(ENV_ROOT_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()

    workspace = _workspace_root(workspace_root)
    if workspace is not None:
        return workspace / ".agents" / "envs" / SKILL_NAME

    root = _resolved_package_root(package_root)
    parts = root.parts
    if ".agents" in parts:
        index = parts.index(".agents")
        agents_root = Path(*parts[: index + 1])
        if os.access(agents_root, os.W_OK):
            return agents_root / "envs" / SKILL_NAME
        return agents_root.parent / ".envs" / SKILL_NAME

    return root.parent / ".envs" / SKILL_NAME


def default_env_prefix(
    package_root: str | Path | None = None,
    env_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    root = _resolved_package_root(package_root)
    store = Path(env_root).expanduser().resolve() if env_root else default_env_store(root, workspace_root)
    return store / spec_sha256(root)[:12]


def env_python(env_prefix: str | Path) -> Path:
    return Path(env_prefix).expanduser().resolve() / "bin" / "python"


def seed_workspace_root_from_argv(argv: list[str] | None = None, *, option: str = "--root") -> None:
    if os.environ.get(WORKSPACE_ROOT_OVERRIDE):
        return
    args = list(sys.argv[1:] if argv is None else argv)
    root = _arg_value(args, option)
    if root:
        os.environ[WORKSPACE_ROOT_OVERRIDE] = root


def _arg_value(args: list[str], option: str) -> str | None:
    for index, arg in enumerate(args):
        if arg == option and index + 1 < len(args):
            return args[index + 1]
        prefix = f"{option}="
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


def load_manifest(
    package_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = runtime_manifest_path(package_root, runtime_home, workspace_root, manifest_path)
    return _load_manifest_file(path)


def _load_manifest_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_VERSION:
        return None
    return data


def write_manifest(
    package_root: str | Path,
    manifest: dict[str, Any],
    runtime_home: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    path = runtime_manifest_path(package_root, runtime_home, workspace_root, manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def configured_python(
    package_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> Path | None:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()

    manifest = load_manifest(package_root, runtime_home, workspace_root, manifest_path)
    if not manifest:
        return None
    if not _manifest_matches_spec(package_root, manifest):
        return None
    python = manifest.get("python_executable")
    if not python:
        return None
    path = Path(str(python)).expanduser().resolve()
    return path if path.exists() else None


def _manifest_matches_spec(package_root: str | Path | None, manifest: dict[str, Any]) -> bool:
    expected = manifest.get("spec_sha256")
    if not expected:
        return True
    spec = environment_spec_path(package_root)
    if not spec.exists():
        return False
    return str(expected) == spec_sha256(package_root)


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
