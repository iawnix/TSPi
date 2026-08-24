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
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

ENV_OVERRIDE = "TS_AGENT_PYTHON"
DISABLE_REEXEC = "TS_AGENT_DISABLE_RUNTIME_REEXEC"
ENV_ROOT_OVERRIDE = "TS_AGENT_ENV_ROOT"
RUNTIME_HOME_OVERRIDE = "TS_AGENT_RUNTIME_HOME"
RUNTIME_MANIFEST_OVERRIDE = "TS_AGENT_RUNTIME_MANIFEST"
WORKSPACE_ROOT_OVERRIDE = "TS_WORKSPACE_ROOT"
MANIFEST_VERSION = "ts-agent-runtime-v2"
RUNTIME_PROBE_VERSION = "ts-runtime-probe/1"
SKILL_NAME = "transition-state-workflow"
PACKAGE_SKILL_PATH = Path("skills") / SKILL_NAME / "SKILL.md"


class RuntimeEnvironmentError(RuntimeError):
    """The installation-owned Python runtime cannot be used safely."""


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


def seed_installation_runtime_from_entrypoint(
    entrypoint: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Bind runtime paths for a script invoked through an installed `current`."""

    stable = Path(os.path.abspath(os.fspath(Path(entrypoint).expanduser())))
    selected = stable.parent.parent
    package_home = selected.parent
    packages_root = package_home.parent
    pi_root = packages_root.parent
    if (
        stable.parent.name != "scripts"
        or selected.name != "current"
        or package_home.name != "ts-agent"
        or packages_root.name != "packages"
        or pi_root.name != ".pi"
    ):
        return None
    installation_root = pi_root.parent
    runtime_home = installation_root / ".agents" / "runtime" / SKILL_NAME
    values = os.environ if environ is None else environ
    values.setdefault(RUNTIME_HOME_OVERRIDE, str(runtime_home))
    values.setdefault(RUNTIME_MANIFEST_OVERRIDE, str(runtime_home / "env.json"))
    values.setdefault(
        ENV_ROOT_OVERRIDE,
        str(installation_root / ".agents" / "envs" / SKILL_NAME),
    )
    return installation_root


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


def require_runtime_python(
    package_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    """Return an executable managed Python or fail without a host fallback."""

    python = configured_python(package_root, runtime_home, workspace_root, manifest_path)
    if python is None:
        manifest = runtime_manifest_path(package_root, runtime_home, workspace_root, manifest_path)
        raise RuntimeEnvironmentError(
            f"managed TS Python runtime is missing or stale: {manifest}; "
            "reinstall the package runtime with scripts/install_env.py"
        )
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeEnvironmentError(f"managed TS Python is not executable: {python}")
    return python


def _manifest_matches_spec(package_root: str | Path | None, manifest: dict[str, Any]) -> bool:
    expected = manifest.get("spec_sha256")
    if not isinstance(expected, str) or not expected:
        return False
    spec = environment_spec_path(package_root)
    if not spec.exists():
        return False
    if expected != spec_sha256(package_root):
        return False
    probe = manifest.get("runtime_probe")
    if not isinstance(probe, dict):
        return False
    if probe.get("schema_version") != RUNTIME_PROBE_VERSION or probe.get("ok") is not True:
        return False
    capabilities = probe.get("capabilities")
    required = ("rdkit_smiles_parse", "rdkit_etkdg_embed", "rdkit_uff_optimize")
    if not isinstance(capabilities, dict) or not all(
        capabilities.get(name) is True for name in required
    ):
        return False
    env_prefix = manifest.get("env_prefix")
    python_executable = manifest.get("python_executable")
    probe_python = probe.get("python")
    modules = probe.get("modules")
    if not all(isinstance(value, str) and value for value in (env_prefix, python_executable)):
        return False
    if not isinstance(probe_python, dict) or not isinstance(probe_python.get("executable"), str):
        return False
    prefix = Path(str(env_prefix)).expanduser().resolve()
    executable = Path(str(python_executable)).expanduser().resolve()
    if Path(str(probe_python["executable"])).expanduser().resolve() != executable:
        return False
    if not executable.is_relative_to(prefix) or not isinstance(modules, dict):
        return False
    for name in ("numpy", "rdkit"):
        module = modules.get(name)
        if not isinstance(module, dict):
            return False
        version = module.get("version")
        origin = module.get("origin")
        if not isinstance(version, str) or not version or not isinstance(origin, str):
            return False
        module_path = Path(origin).expanduser().resolve()
        if not module_path.is_file() or not module_path.is_relative_to(prefix):
            return False
    return True


def ensure_runtime_python(
    package_root: str | Path | None = None,
    *,
    required: bool = False,
) -> Path | None:
    """Re-exec with the configured runtime Python, optionally failing closed."""

    python = require_runtime_python(package_root) if required else configured_python(package_root)
    if python is None:
        return None

    if os.environ.get(DISABLE_REEXEC) == "1":
        if required and Path(sys.executable).resolve() != python:
            raise RuntimeEnvironmentError(
                "managed TS Python is required but runtime re-exec is disabled"
            )
        return python

    current = Path(sys.executable).resolve()
    if current == python:
        return python

    os.execv(str(python), [str(python), *sys.argv])
    return None


def bind_runtime_process_environment(python: str | Path) -> None:
    """Bind Python commands in the current process tree to the managed runtime."""

    executable = Path(python).expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeEnvironmentError(f"managed TS Python is not executable: {executable}")
    bin_directory = str(executable.parent)
    existing = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    os.environ["PATH"] = os.pathsep.join(
        [bin_directory, *(item for item in existing if item != bin_directory)]
    )
    os.environ[ENV_OVERRIDE] = str(executable)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ.pop("PYTHONHOME", None)
