"""Configuration for local and remote compute environments."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ts_agent.remote.config import parse_environment as parse_remote_environment
from ts_agent.remote.errors import RemoteConfigurationError
from ts_agent.remote.models import RemotePlatform


CONFIG_ENV = "TS_COMPUTE_CONFIG"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvironmentConfigurationError(ValueError):
    """Raised when compute environment configuration is absent or invalid."""


@dataclass(frozen=True)
class BackendBinding:
    command: tuple[str, ...]
    activation_script: str | None = None
    scratch_root: str | None = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ComputeEnvironment:
    name: str
    kind: str
    backends: dict[str, BackendBinding]
    platform: RemotePlatform | None = None


@dataclass(frozen=True)
class EnvironmentConfig:
    source: Path
    default_environment: str
    environments: dict[str, ComputeEnvironment]

    def environment(self, name: str | None = None, *, kind: str | None = None) -> ComputeEnvironment:
        selected = name or self.default_environment
        try:
            environment = self.environments[selected]
        except KeyError as exc:
            raise EnvironmentConfigurationError(f"unknown compute environment: {selected}") from exc
        if name is None and kind is not None and environment.kind != kind:
            candidates = [item for item in self.environments.values() if item.kind == kind]
            if len(candidates) == 1:
                return candidates[0]
            if not candidates:
                raise EnvironmentConfigurationError(f"no {kind} compute environment is configured")
            raise EnvironmentConfigurationError(
                f"multiple {kind} compute environments are configured; select one by name"
            )
        if kind is not None and environment.kind != kind:
            raise EnvironmentConfigurationError(
                f"compute environment {selected!r} has kind={environment.kind!r}, expected {kind!r}"
            )
        return environment


def configured_path() -> Path:
    raw = os.environ.get(CONFIG_ENV, "").strip()
    if not raw:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            raw = str(Path(install_root) / ".pi" / "compute.toml")
    if not raw:
        raise EnvironmentConfigurationError(f"{CONFIG_ENV} is not configured")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise EnvironmentConfigurationError(f"{CONFIG_ENV} must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise EnvironmentConfigurationError(f"{CONFIG_ENV} is not a regular file: {path}")
    return path.resolve(strict=True)


def load_config(path: str | Path | None = None) -> EnvironmentConfig:
    source = Path(path).expanduser().resolve(strict=True) if path is not None else configured_path()
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EnvironmentConfigurationError(f"cannot read compute configuration {source}: {exc}") from exc
    environments_raw = _mapping(raw.get("environments"), "environments")
    if not environments_raw:
        raise EnvironmentConfigurationError("compute config must define at least one environment")
    environments: dict[str, ComputeEnvironment] = {}
    for name, value in environments_raw.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise EnvironmentConfigurationError(f"invalid compute environment name: {name!r}")
        environments[name] = _environment(
            name,
            _mapping(value, f"environments.{name}"),
            source.parent,
        )
    default = raw.get("default_environment")
    if not isinstance(default, str) or default not in environments:
        raise EnvironmentConfigurationError("default_environment must name one configured environment")
    return EnvironmentConfig(
        source=source,
        default_environment=default,
        environments=environments,
    )


def _environment(name: str, raw: dict[str, Any], base: Path) -> ComputeEnvironment:
    kind = raw.get("kind")
    if kind not in {"local", "remote"}:
        raise EnvironmentConfigurationError(
            f"environments.{name}.kind must explicitly be local or remote"
        )
    backends_raw = _mapping(raw.get("backends"), f"environments.{name}.backends")
    backends = {
        backend: _backend_binding(
            backend,
            _mapping(value, f"environments.{name}.backends.{backend}"),
            kind,
        )
        for backend, value in backends_raw.items()
    }
    platform = None
    if kind == "remote":
        try:
            platform = parse_remote_environment(name, raw, base)
        except RemoteConfigurationError as exc:
            raise EnvironmentConfigurationError(str(exc)) from exc
        backends = {
            backend: BackendBinding(
                command=value.command,
                activation_script=value.activation_script,
                scratch_root=value.scratch_root,
                environment=dict(value.environment),
            )
            for backend, value in platform.backends.items()
        }
    return ComputeEnvironment(name=name, kind=kind, backends=backends, platform=platform)


def _backend_binding(name: str, raw: dict[str, Any], kind: str) -> BackendBinding:
    command = raw.get("command")
    if kind == "local":
        if not isinstance(command, str) or not command.strip() or any(ord(char) < 32 for char in command):
            raise EnvironmentConfigurationError(f"backends.{name}.command must be a non-empty string")
        normalized = (command.strip(),)
    else:
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise EnvironmentConfigurationError(f"backends.{name}.command must be a non-empty string array")
        normalized = tuple(command)
    activation = _optional_path(raw.get("activation_script"), f"backends.{name}.activation_script", kind)
    scratch = _optional_path(raw.get("scratch_root"), f"backends.{name}.scratch_root", kind)
    environment_raw = _mapping(raw.get("environment"), f"backends.{name}.environment")
    environment: dict[str, str] = {}
    for key, value in environment_raw.items():
        if not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\x00" in value:
            raise EnvironmentConfigurationError(f"backends.{name}.environment contains an invalid entry")
        environment[key] = value
    return BackendBinding(normalized, activation, scratch, environment)


def _optional_path(value: Any, label: str, kind: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise EnvironmentConfigurationError(f"{label} must be a path string")
    if kind == "local":
        path = Path(value).expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
            raise EnvironmentConfigurationError(f"{label} must be an absolute readable regular file")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise EnvironmentConfigurationError(f"{label} must be a TOML table")
    return value
