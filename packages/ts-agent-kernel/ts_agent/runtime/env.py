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
from pathlib import Path, PurePosixPath
from typing import Any

ENV_OVERRIDE = "TS_AGENT_PYTHON"
DISABLE_REEXEC = "TS_AGENT_DISABLE_RUNTIME_REEXEC"
ENV_ROOT_OVERRIDE = "TS_AGENT_ENV_ROOT"
RUNTIME_HOME_OVERRIDE = "TS_AGENT_RUNTIME_HOME"
RUNTIME_MANIFEST_OVERRIDE = "TS_AGENT_RUNTIME_MANIFEST"
PACKAGE_ROOT_OVERRIDE = "TS_PACKAGE_ROOT"
WORKSPACE_ROOT_OVERRIDE = "TS_WORKSPACE_ROOT"
MANIFEST_VERSION = "ts-agent-runtime/3"
RUNTIME_PROBE_VERSION = "ts-runtime-probe/3"
PACKAGE_NAMESPACE = "tspi"
CORE_SKILL_NAME = "tspi-orchestration"
BASE_ENV_DIRECTORY = "base"
KERNEL_ENV_DIRECTORY = "kernels"
PACKAGE_SKILL_PATH = Path("skills") / CORE_SKILL_NAME / "SKILL.md"
PYTHON_DISTRIBUTION = "ts-agent-kernel"
PYTHON_SOURCE_ROOT = Path("packages") / "ts-agent-kernel"
PYTHON_PACKAGE_NAME = "ts_agent"
PYTHON_PAYLOAD_SUFFIXES = frozenset({".css", ".html", ".js", ".json", ".py", ".svg", ".toml"})


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
    raise RuntimeEnvironmentError(f"cannot locate TS Agent package root from: {path}")


def seed_installation_runtime(
    installation_root: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
    authoritative: bool = False,
) -> Path:
    """Bind runtime paths owned by one TSPi installation root."""

    root = Path(installation_root).expanduser().resolve()
    runtime_home = root / ".agents" / "runtime" / PACKAGE_NAMESPACE
    values = os.environ if environ is None else environ
    bindings = {
        RUNTIME_HOME_OVERRIDE: str(runtime_home),
        RUNTIME_MANIFEST_OVERRIDE: str(runtime_home / "env.json"),
        ENV_ROOT_OVERRIDE: str(root / ".agents" / "envs" / PACKAGE_NAMESPACE),
    }
    for name, value in bindings.items():
        if authoritative:
            values[name] = value
        else:
            values.setdefault(name, value)
    return root


def seed_installation_runtime_from_entrypoint(
    entrypoint: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Bind runtime paths for a script invoked through an installed release."""

    stable = Path(os.path.abspath(os.fspath(Path(entrypoint).expanduser())))
    installation_root = _suite_installation_root(stable)
    if installation_root is None:
        return None
    return seed_installation_runtime(installation_root, environ=environ)


def _suite_installation_root(stable: Path) -> Path | None:
    """Recognize a validated unified-suite Web or provider entrypoint."""

    if stable.name == "TSWeb":
        installation_root = stable.parent
        selected_root = installation_root / ".pi" / "packages" / "tspi" / "current"
        selected_paths = (
            selected_root / "web" / "bin" / "ts-web",
        )
        try:
            resolved_stable = stable.resolve(strict=True)
        except OSError:
            return None
        for selected in selected_paths:
            try:
                if resolved_stable == selected.resolve(strict=True):
                    break
            except OSError:
                continue
        else:
            return None
    else:
        scripts = stable.parent
        owner = scripts.parent
        selected_release = owner.parent
        package_home = selected_release.parent
        packages_root = package_home.parent
        pi_root = packages_root.parent
        if (
            stable.name not in {"ts_web_provider.py", "ts-web"}
            or scripts.name not in {"scripts", "bin"}
            or owner.name not in {"agent", "web"}
            or selected_release.name != "current"
            or package_home.name != "tspi"
            or packages_root.name != "packages"
            or pi_root.name != ".pi"
        ):
            return None
        installation_root = pi_root.parent

    try:
        resolved = stable.resolve(strict=True)
    except OSError:
        return None
    releases_root = installation_root / ".pi" / "packages" / "tspi" / "releases"
    try:
        relative = resolved.relative_to(releases_root)
    except ValueError:
        return None
    if len(relative.parts) != 4 or tuple(relative.parts[1:]) not in {
        ("agent", "scripts", "ts_web_provider.py"),
        ("web", "bin", "ts-web"),
    }:
        return None
    return installation_root


def environment_spec_path(package_root: str | Path | None = None) -> Path:
    root = resolve_package_root(package_root)
    return root / "environment.yml"


def runtime_requirements_path(package_root: str | Path | None = None) -> Path:
    root = resolve_package_root(package_root)
    return root / "requirements-runtime.txt"


def spec_sha256(package_root: str | Path | None = None) -> str:
    environment_spec = environment_spec_path(package_root)
    pip_requirements = runtime_requirements_path(package_root)
    return payload_records_sha256(
        [
            (environment_spec.name, environment_spec.read_bytes()),
            (pip_requirements.name, pip_requirements.read_bytes()),
        ]
    )


def package_version(package_root: str | Path | None = None) -> str:
    path = resolve_package_root(package_root) / "package.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeEnvironmentError(f"cannot read package version from {path}") from exc
    version = value.get("version") if isinstance(value, dict) else None
    if not isinstance(version, str) or not version:
        raise RuntimeEnvironmentError(f"package version is missing from {path}")
    return version


def python_payload_sha256(
    package_root: str | Path | None = None,
) -> str:
    """Hash the source files that are installed into the Python distribution."""

    package = resolve_package_root(package_root)
    root = package / PYTHON_SOURCE_ROOT
    if not root.is_dir():
        raise RuntimeEnvironmentError(f"Python source root is missing: {root}")
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if not _is_python_payload_path(relative):
            continue
        records.append((relative.as_posix(), path.read_bytes()))
    if not records:
        raise RuntimeEnvironmentError(f"Python source payload is empty: {root}")
    return payload_records_sha256(records)


def payload_records_sha256(records: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(records):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _is_python_payload_path(path: PurePosixPath) -> bool:
    return (
        bool(path.parts)
        and path.parts[0] == PYTHON_PACKAGE_NAME
        and (len(path.parts) < 2 or path.parts[1] != "web")
        and "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix in PYTHON_PAYLOAD_SUFFIXES
    )


def resolve_package_root(package_root: str | Path | None = None) -> Path:
    """Resolve an explicit or process-bound Pi Package root."""

    root = package_root or os.environ.get(PACKAGE_ROOT_OVERRIDE)
    return Path(root).expanduser().resolve() if root else package_root_from_file(__file__)


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
        return workspace / ".agents" / "runtime" / PACKAGE_NAMESPACE

    root = resolve_package_root(package_root)
    parts = root.parts
    if ".agents" in parts:
        index = parts.index(".agents")
        agents_root = Path(*parts[: index + 1])
        return agents_root / "runtime" / PACKAGE_NAMESPACE

    return root.parent / ".runtime" / PACKAGE_NAMESPACE


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
        return workspace / ".agents" / "envs" / PACKAGE_NAMESPACE

    root = resolve_package_root(package_root)
    parts = root.parts
    if ".agents" in parts:
        index = parts.index(".agents")
        agents_root = Path(*parts[: index + 1])
        if os.access(agents_root, os.W_OK):
            return agents_root / "envs" / PACKAGE_NAMESPACE
        return agents_root.parent / ".envs" / PACKAGE_NAMESPACE

    return root.parent / ".envs" / PACKAGE_NAMESPACE


def default_env_prefix(
    package_root: str | Path | None = None,
    env_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    root = resolve_package_root(package_root)
    store = Path(env_root).expanduser().resolve() if env_root else default_env_store(root, workspace_root)
    return store / BASE_ENV_DIRECTORY / spec_sha256(root)[:12]


def default_kernel_prefix(
    package_root: str | Path | None = None,
    env_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    payload_sha256: str | None = None,
) -> Path:
    """Return the release overlay path for one exact Python payload."""

    root = resolve_package_root(package_root)
    store = Path(env_root).expanduser().resolve() if env_root else default_env_store(root, workspace_root)
    digest = payload_sha256 or python_payload_sha256(root)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeEnvironmentError("Python payload digest is not a lowercase SHA-256 value")
    return store / KERNEL_ENV_DIRECTORY / digest[:16]


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
    requirements = runtime_requirements_path(package_root)
    if not spec.exists() or not requirements.exists():
        return False
    source_payload = manifest.get("python_payload_sha256")
    if not isinstance(source_payload, str) or not source_payload:
        return False
    try:
        if expected != spec_sha256(package_root):
            return False
        if source_payload != python_payload_sha256(package_root):
            return False
        current_package_version = package_version(package_root)
    except (OSError, RuntimeEnvironmentError):
        return False
    probe = manifest.get("runtime_probe")
    if not isinstance(probe, dict):
        return False
    if probe.get("schema_version") != RUNTIME_PROBE_VERSION or probe.get("ok") is not True:
        return False
    capabilities = probe.get("capabilities")
    required = (
        "rdkit_smiles_parse",
        "rdkit_etkdg_embed",
        "rdkit_uff_optimize",
        "matplotlib_render",
        "xyzrender_cli",
    )
    if not isinstance(capabilities, dict) or not all(
        capabilities.get(name) is True for name in required
    ):
        return False
    env_prefix = manifest.get("env_prefix")
    kernel_env_prefix = manifest.get("kernel_env_prefix")
    base_python_executable = manifest.get("base_python_executable")
    python_executable = manifest.get("python_executable")
    probe_python = probe.get("python")
    modules = probe.get("modules")
    distribution = probe.get("distribution")
    commands = probe.get("commands")
    if not all(
        isinstance(value, str) and value
        for value in (
            env_prefix,
            kernel_env_prefix,
            base_python_executable,
            python_executable,
        )
    ):
        return False
    if not isinstance(probe_python, dict) or not isinstance(probe_python.get("executable"), str):
        return False
    prefix = Path(str(env_prefix)).expanduser().resolve()
    kernel_prefix = Path(str(kernel_env_prefix)).expanduser().resolve()
    base_python = Path(str(base_python_executable)).expanduser().resolve()
    executable = Path(str(python_executable)).expanduser().resolve()
    if Path(str(probe_python["executable"])).expanduser().resolve() != executable:
        return False
    if (
        prefix == kernel_prefix
        or kernel_prefix.is_relative_to(prefix)
        or prefix.is_relative_to(kernel_prefix)
        or not base_python.is_file()
        or not base_python.is_relative_to(prefix)
        or not executable.is_relative_to(kernel_prefix)
        or not isinstance(modules, dict)
        or not isinstance(distribution, dict)
        or not isinstance(commands, dict)
    ):
        return False
    if (
        distribution.get("name") != PYTHON_DISTRIBUTION
        or distribution.get("installed") is not True
        or distribution.get("version") != current_package_version
        or distribution.get("payload_sha256") != source_payload
    ):
        return False
    distribution_root = distribution.get("root")
    if not isinstance(distribution_root, str):
        return False
    if not Path(distribution_root).expanduser().resolve().is_relative_to(kernel_prefix):
        return False
    for name in ("numpy", "rdkit", "matplotlib"):
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
    xyzrender = commands.get("xyzrender")
    if not isinstance(xyzrender, dict):
        return False
    renderer_path = xyzrender.get("path")
    renderer_version = xyzrender.get("version")
    if not isinstance(renderer_path, str) or not isinstance(renderer_version, str) or not renderer_version:
        return False
    renderer = Path(renderer_path).expanduser().resolve()
    if not renderer.is_file() or not os.access(renderer, os.X_OK) or not renderer.is_relative_to(prefix):
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
