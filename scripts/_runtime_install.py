"""Prepare, probe, and publish the managed scientific runtime used by TSPi."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

try:
    from ._bootstrap import load_runtime_environment
    from ._wheel import build_wheel, release_wheel
except ImportError:
    from _bootstrap import load_runtime_environment
    from _wheel import build_wheel, release_wheel


class RuntimeInstallError(RuntimeError):
    """The managed runtime could not be prepared or safely published."""


@dataclass(frozen=True)
class PreparedRuntime:
    """A probed runtime whose manifest has not necessarily been published."""

    package_root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    result: dict[str, Any]
    runtime_environment: ModuleType


def install_runtime(
    package_root: str | Path,
    *,
    workspace_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    manifest_path: str | Path | None = None,
    env_root: str | Path | None = None,
    conda: str | None = None,
    conda_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Prepare, probe, and publish one complete managed runtime."""

    prepared = prepare_runtime(
        package_root,
        workspace_root=workspace_root,
        runtime_home=runtime_home,
        manifest_path=manifest_path,
        env_root=env_root,
        conda=conda,
        conda_root=conda_root,
        force=force,
    )
    publish_runtime(prepared)
    return dict(prepared.result)


def plan_runtime(
    package_root: str | Path,
    *,
    workspace_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    manifest_path: str | Path | None = None,
    env_root: str | Path | None = None,
    conda: str | None = None,
    conda_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Resolve all managed runtime paths without mutating them."""

    paths = _runtime_paths(
        package_root,
        workspace_root=workspace_root,
        runtime_home=runtime_home,
        manifest_path=manifest_path,
        env_root=env_root,
    )
    bundled = release_wheel(paths["package_root"])
    conda_root_path = _resolve_conda_root(conda_root)
    conda_executable = _resolve_conda(conda, conda_root_path)
    base_action = _base_action(paths["base_prefix"], paths["base_python"], force)
    kernel_action = _kernel_action(paths["kernel_prefix"], paths["kernel_python"], force)
    result = _result_payload(
        paths,
        bundled=bundled,
        conda_root=conda_root_path,
        conda=conda_executable,
        base_action=base_action,
        kernel_action=kernel_action,
        dry_run=True,
    )
    return result


def prepare_runtime(
    package_root: str | Path,
    *,
    workspace_root: str | Path | None = None,
    runtime_home: str | Path | None = None,
    manifest_path: str | Path | None = None,
    env_root: str | Path | None = None,
    conda: str | None = None,
    conda_root: str | Path | None = None,
    force: bool = False,
) -> PreparedRuntime:
    """Create and probe the runtime without publishing its shared manifest."""

    paths = _runtime_paths(
        package_root,
        workspace_root=workspace_root,
        runtime_home=runtime_home,
        manifest_path=manifest_path,
        env_root=env_root,
    )
    bundled = release_wheel(paths["package_root"])
    conda_root_path = _resolve_conda_root(conda_root)
    conda_executable = _resolve_conda(conda, conda_root_path)
    base_action = _base_action(paths["base_prefix"], paths["base_python"], force)
    kernel_action = _kernel_action(paths["kernel_prefix"], paths["kernel_python"], force)

    if base_action != "reuse" and conda_executable is None:
        raise RuntimeInstallError(
            "conda or mamba not found; set --conda, --conda-root, "
            "TS_AGENT_CONDA_EXE, or TS_AGENT_CONDA_ROOT"
        )
    base_action = _prepare_base(
        conda_executable,
        paths["base_prefix"],
        paths["base_python"],
        paths["spec_path"],
        paths["requirements_path"],
        paths["package_root"],
        base_action,
    )
    existing_probe: dict[str, Any] | None = None
    if kernel_action == "reuse":
        try:
            existing_probe = _run_runtime_probe(paths["kernel_python"], paths["package_root"])
        except RuntimeInstallError as exc:
            raise RuntimeInstallError(
                f"existing kernel overlay is stale or damaged: {paths['kernel_prefix']}; "
                "rerun with --force to recreate this exact overlay"
            ) from exc

    with _resolved_wheel(paths["package_root"], paths["base_python"], bundled) as (wheel, descriptor):
        if kernel_action != "reuse":
            if kernel_action == "recreate":
                _remove_managed_kernel(paths["kernel_prefix"], paths["env_store"])
            _create_kernel_overlay(paths["base_python"], paths["kernel_prefix"], paths["env_store"])
            completed = _pip_install_wheel(paths["kernel_python"], wheel, paths["package_root"])
            if completed.returncode != 0:
                _remove_managed_kernel(paths["kernel_prefix"], paths["env_store"])
                raise RuntimeInstallError("failed to install ts-agent-kernel into the release overlay")
            runtime_probe = _run_runtime_probe(paths["kernel_python"], paths["package_root"])
        else:
            runtime_probe = existing_probe
            if runtime_probe is None:
                raise RuntimeInstallError("existing kernel overlay was not probed")

        distribution_install = dict(descriptor)
        manifest = _runtime_manifest(
            paths,
            distribution_install,
            runtime_probe,
            conda_root=conda_root_path,
            conda=conda_executable,
        )
        runtime = paths["runtime_environment"]
        if not runtime._manifest_matches_spec(paths["package_root"], manifest):
            if kernel_action != "reuse":
                _remove_managed_kernel(paths["kernel_prefix"], paths["env_store"])
            raise RuntimeInstallError("prepared runtime does not satisfy the package and environment contract")

    result = _result_payload(
        paths,
        bundled=bundled,
        conda_root=conda_root_path,
        conda=conda_executable,
        base_action=base_action,
        kernel_action=kernel_action,
        dry_run=False,
    )
    result["python_wheel"] = distribution_install
    result["runtime_probe"] = runtime_probe
    return PreparedRuntime(
        package_root=paths["package_root"],
        manifest_path=paths["manifest_path"],
        manifest=manifest,
        result=result,
        runtime_environment=paths["runtime_environment"],
    )


def publish_runtime(prepared: PreparedRuntime) -> Path:
    """Atomically publish the manifest for an already probed runtime."""

    path = prepared.runtime_environment.write_manifest(
        prepared.package_root,
        prepared.manifest,
        manifest_path=prepared.manifest_path,
    )
    if path != prepared.manifest_path:
        raise RuntimeInstallError("runtime manifest was published to an unexpected path")
    return path


def _runtime_paths(
    package_root: str | Path,
    *,
    workspace_root: str | Path | None,
    runtime_home: str | Path | None,
    manifest_path: str | Path | None,
    env_root: str | Path | None,
) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    spec_path = root / "environment.yml"
    if not spec_path.is_file() or spec_path.is_symlink():
        raise RuntimeInstallError(f"missing or unsafe environment spec: {spec_path}")
    runtime = load_runtime_environment(root)
    requirements_path = runtime.runtime_requirements_path(root)
    if not requirements_path.is_file() or requirements_path.is_symlink():
        raise RuntimeInstallError(
            f"missing or unsafe runtime pip requirements: {requirements_path}"
        )
    payload_sha256 = runtime.python_payload_sha256(root)
    store = (
        Path(env_root).expanduser().resolve()
        if env_root
        else runtime.default_env_store(root, workspace_root)
    )
    base_prefix = runtime.default_env_prefix(root, store, workspace_root)
    kernel_prefix = runtime.default_kernel_prefix(
        root,
        store,
        workspace_root,
        payload_sha256=payload_sha256,
    )
    resolved_runtime_home = (
        Path(runtime_home).expanduser().resolve()
        if runtime_home
        else runtime.default_runtime_home(root, workspace_root)
    )
    resolved_manifest = runtime.runtime_manifest_path(
        root,
        runtime_home=runtime_home,
        workspace_root=workspace_root,
        manifest_path=manifest_path,
    )
    return {
        "runtime_environment": runtime,
        "package_root": root,
        "spec_path": spec_path,
        "requirements_path": requirements_path,
        "spec_sha256": runtime.spec_sha256(root),
        "payload_sha256": payload_sha256,
        "env_store": store,
        "base_prefix": base_prefix,
        "base_python": runtime.env_python(base_prefix),
        "kernel_prefix": kernel_prefix,
        "kernel_python": runtime.env_python(kernel_prefix),
        "runtime_home": resolved_runtime_home,
        "manifest_path": resolved_manifest,
    }


def _base_action(prefix: Path, python: Path, force: bool) -> str:
    if force and (prefix.exists() or prefix.is_symlink()):
        return "update"
    if python.is_file():
        return "reuse"
    return "update" if prefix.exists() or prefix.is_symlink() else "create"


def _kernel_action(prefix: Path, python: Path, force: bool) -> str:
    if force and (prefix.exists() or prefix.is_symlink()):
        return "recreate"
    if python.is_file():
        return "reuse"
    if prefix.exists() or prefix.is_symlink():
        raise RuntimeInstallError(
            f"kernel overlay exists without an interpreter: {prefix}; rerun with --force"
        )
    return "create"


def _prepare_base(
    conda: str | None,
    prefix: Path,
    python: Path,
    spec_path: Path,
    requirements_path: Path,
    package_root: Path,
    action: str,
) -> str:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    effective_action = action
    if action == "reuse":
        try:
            _run_base_probe(python, package_root)
        except RuntimeInstallError as error:
            if conda is None:
                raise RuntimeInstallError(
                    f"existing scientific base is stale or damaged: {prefix}; "
                    f"conda or mamba is required to repair it: {error}"
                ) from error
            effective_action = "update"
    if effective_action != "reuse":
        if conda is None:
            raise RuntimeInstallError("Conda is required to create or update the scientific base")
        completed = subprocess.run(
            _conda_env_command(conda, effective_action, prefix, spec_path),
            text=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeInstallError(
                f"Conda {effective_action} failed with exit code {completed.returncode}"
            )
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeInstallError(f"scientific base Python is missing or not executable: {python}")
    if effective_action != "reuse":
        completed = _pip_install_requirements(python, requirements_path, package_root)
        if completed.returncode != 0:
            raise RuntimeInstallError(
                "scientific base pip dependency installation failed "
                f"with exit code {completed.returncode}"
            )
        try:
            _run_base_probe(python, package_root)
        except RuntimeInstallError as error:
            raise RuntimeInstallError(
                f"scientific base failed its required capability probe: {prefix}: {error}"
            ) from error
    return effective_action


def _create_kernel_overlay(base_python: Path, prefix: Path, env_store: Path) -> None:
    _validate_managed_kernel_path(prefix, env_store)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    if prefix.exists() or prefix.is_symlink():
        raise RuntimeInstallError(f"refusing to overwrite an existing kernel overlay: {prefix}")
    completed = subprocess.run(
        [
            str(base_python),
            "-m",
            "venv",
            "--copies",
            "--system-site-packages",
            str(prefix),
        ],
        text=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
        check=False,
    )
    if completed.returncode != 0:
        if prefix.exists() or prefix.is_symlink():
            _remove_managed_kernel(prefix, env_store)
        raise RuntimeInstallError(f"kernel overlay creation failed with exit code {completed.returncode}")


def _remove_managed_kernel(prefix: Path, env_store: Path) -> None:
    _validate_managed_kernel_path(prefix, env_store)
    if prefix.is_symlink() or prefix.is_file():
        prefix.unlink()
    elif prefix.exists():
        shutil.rmtree(prefix)


def _validate_managed_kernel_path(prefix: Path, env_store: Path) -> None:
    expected_parent = env_store / "kernels"
    if prefix.parent != expected_parent or len(prefix.name) != 16 or any(
        character not in "0123456789abcdef" for character in prefix.name
    ):
        raise RuntimeInstallError(f"refusing to modify an unmanaged kernel path: {prefix}")


@contextmanager
def _resolved_wheel(
    package_root: Path,
    build_python: Path,
    bundled: tuple[Path, dict[str, Any]] | None,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    if bundled is not None:
        yield bundled
        return
    with tempfile.TemporaryDirectory(prefix="ts-agent-install-wheel-") as temporary:
        wheel_dir = Path(temporary)
        descriptor = build_wheel(package_root, wheel_dir, python=build_python)
        wheel = wheel_dir / descriptor["filename"]
        yield wheel, {**descriptor, "source": "source-wheel-build"}


def _pip_install_wheel(
    python: Path,
    wheel: Path,
    package_root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-cache-dir",
            "--force-reinstall",
            str(wheel),
        ],
        cwd=package_root,
        env=_clean_python_environment(),
        text=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
        check=False,
    )


def _pip_install_requirements(
    python: Path,
    requirements_path: Path,
    package_root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--requirement",
            str(requirements_path),
        ],
        cwd=package_root,
        env=_clean_python_environment(),
        text=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
        check=False,
    )


def _run_runtime_probe(python: Path, package_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(python), "-m", "ts_agent.runtime.probe", "--json"],
        cwd=package_root,
        env=_clean_python_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return _parse_probe_result(completed)


def _run_base_probe(python: Path, package_root: Path) -> dict[str, Any]:
    source_root = package_root / "packages" / "ts-agent-kernel"
    program = (
        "import json,sys;"
        "sys.path.insert(0,sys.argv[1]);"
        "from ts_agent.runtime.probe import probe_runtime_capabilities;"
        "print(json.dumps(probe_runtime_capabilities(require_distribution=False),sort_keys=True))"
    )
    completed = subprocess.run(
        [str(python), "-c", program, str(source_root)],
        cwd=package_root,
        env=_clean_python_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return _parse_probe_result(completed)


def _parse_probe_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "probe process failed"
        raise RuntimeInstallError(detail)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeInstallError("probe did not return valid JSON") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeInstallError("probe returned an unhealthy result")
    return result


def _clean_python_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _runtime_manifest(
    paths: dict[str, Any],
    distribution_install: dict[str, Any],
    runtime_probe: dict[str, Any],
    *,
    conda_root: Path | None,
    conda: str | None,
) -> dict[str, Any]:
    runtime = paths["runtime_environment"]
    return {
        "schema_version": runtime.MANIFEST_VERSION,
        "package_root": str(paths["package_root"]),
        "environment_spec": str(paths["spec_path"]),
        "runtime_requirements": str(paths["requirements_path"]),
        "spec_sha256": paths["spec_sha256"],
        "python_payload_sha256": paths["payload_sha256"],
        "python_wheel": distribution_install,
        "env_prefix": str(paths["base_prefix"]),
        "base_python_executable": str(paths["base_python"]),
        "kernel_env_prefix": str(paths["kernel_prefix"]),
        "python_executable": str(paths["kernel_python"]),
        "runtime_home": str(paths["runtime_home"]),
        "manifest_path": str(paths["manifest_path"]),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "runtime_probe": runtime_probe,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _result_payload(
    paths: dict[str, Any],
    *,
    bundled: tuple[Path, dict[str, Any]] | None,
    conda_root: Path | None,
    conda: str | None,
    base_action: str,
    kernel_action: str,
    dry_run: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "package_root": str(paths["package_root"]),
        "environment_spec": str(paths["spec_path"]),
        "runtime_requirements": str(paths["requirements_path"]),
        "spec_sha256": paths["spec_sha256"],
        "python_distribution": paths["runtime_environment"].PYTHON_DISTRIBUTION,
        "python_payload_sha256": paths["payload_sha256"],
        "python_install_source": "bundled-release-wheel" if bundled else "source-wheel-build",
        "env_prefix": str(paths["base_prefix"]),
        "base_python_executable": str(paths["base_python"]),
        "kernel_env_prefix": str(paths["kernel_prefix"]),
        "runtime_home": str(paths["runtime_home"]),
        "manifest_path": str(paths["manifest_path"]),
        "python_executable": str(paths["kernel_python"]),
        "conda_root": str(conda_root) if conda_root else None,
        "conda_executable": conda,
        "base_action": base_action,
        "kernel_action": kernel_action,
        "action": kernel_action if base_action == "reuse" else base_action,
        "dry_run": dry_run,
    }
    if bundled is not None:
        result["python_wheel"] = bundled[1]
    return result


def _resolve_conda_root(explicit: str | Path | None) -> Path | None:
    root = explicit or os.environ.get("TS_AGENT_CONDA_ROOT")
    if not root:
        return None
    return Path(root).expanduser().resolve()


def _resolve_conda(explicit: str | None, conda_root: Path | None) -> str | None:
    candidates = [
        explicit,
        *_conda_root_candidates(conda_root),
        os.environ.get("TS_AGENT_CONDA_EXE"),
        *_conda_root_candidates(_resolve_conda_root(None) if conda_root is None else None),
        shutil.which("mamba"),
        shutil.which("conda"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return str(Path(candidate).expanduser().resolve())
    return None


def _conda_root_candidates(conda_root: Path | None) -> list[str]:
    if conda_root is None:
        return []
    return [
        str(conda_root / "bin" / "mamba"),
        str(conda_root / "condabin" / "mamba"),
        str(conda_root / "bin" / "conda"),
        str(conda_root / "condabin" / "conda"),
    ]


def _conda_env_command(conda: str, action: str, prefix: Path, spec_path: Path) -> list[str]:
    command = [conda, "env", action]
    if Path(conda).name == "conda":
        command.extend(["--solver", "libmamba"])
    command.extend(["-p", str(prefix), "-f", str(spec_path)])
    if action == "update":
        command.append("--prune")
    return command
