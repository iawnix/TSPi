"""Unified local/remote compute provider configuration.

One compute profile describes where software is provided and how it is
invoked.  ``kind = "local"`` profiles execute in the workspace host;
``kind = "remote"`` profiles additionally carry the SSH/scheduler contract.

The loader is intentionally small and read-only.  Existing ``local.toml`` and
``remote.toml`` remain supported by their respective compatibility loaders;
new installations can use one ``compute.toml`` instead.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ts_agent.remote.config import parse_profile as parse_remote_profile
from ts_agent.remote.errors import RemoteConfigurationError
from ts_agent.remote.models import RemoteProfile


CONFIG_ENV = "TS_COMPUTE_CONFIG"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ComputeConfigurationError(ValueError):
    """Raised when a unified compute configuration is absent or invalid."""


@dataclass(frozen=True)
class SoftwareProvider:
    command: tuple[str, ...]
    activation_script: str | None = None
    scratch_root: str | None = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ComputeProfile:
    name: str
    kind: str
    software: dict[str, SoftwareProvider]
    remote: RemoteProfile | None = None


@dataclass(frozen=True)
class ComputeConfig:
    source: Path
    default_profile: str
    profiles: dict[str, ComputeProfile]

    def profile(self, name: str | None = None, *, kind: str | None = None) -> ComputeProfile:
        selected = name or self.default_profile
        try:
            profile = self.profiles[selected]
        except KeyError as exc:
            raise ComputeConfigurationError(f"unknown compute profile: {selected}") from exc
        if kind is not None and profile.kind != kind:
            raise ComputeConfigurationError(
                f"compute profile {selected!r} has kind={profile.kind!r}, expected {kind!r}"
            )
        return profile


def configured_path() -> Path:
    raw = os.environ.get(CONFIG_ENV, "").strip()
    if not raw:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            raw = str(Path(install_root) / ".pi" / "compute.toml")
    if not raw:
        raise ComputeConfigurationError(f"{CONFIG_ENV} is not configured")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ComputeConfigurationError(f"{CONFIG_ENV} must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise ComputeConfigurationError(f"{CONFIG_ENV} is not a regular file: {path}")
    return path.resolve(strict=True)


def load_config(path: str | Path | None = None) -> ComputeConfig:
    source = Path(path).expanduser().resolve(strict=True) if path is not None else configured_path()
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ComputeConfigurationError(f"cannot read compute configuration {source}: {exc}") from exc
    profiles_raw = _mapping(raw.get("profiles"), "profiles")
    if not profiles_raw:
        raise ComputeConfigurationError("compute config must define at least one profile")
    profiles: dict[str, ComputeProfile] = {}
    for name, value in profiles_raw.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ComputeConfigurationError(f"invalid compute profile name: {name!r}")
        profiles[name] = _profile(name, _mapping(value, f"profiles.{name}"), source.parent)
    default = raw.get("default_profile")
    if not isinstance(default, str) or default not in profiles:
        raise ComputeConfigurationError("default_profile must name one configured profile")
    return ComputeConfig(source=source, default_profile=default, profiles=profiles)


def _profile(name: str, raw: dict[str, Any], base: Path) -> ComputeProfile:
    kind = raw.get("kind")
    if kind is None:
        # A profile with SSH fields is unambiguously an older-style remote
        # profile.  New files should declare kind explicitly.
        kind = "remote" if any(key in raw for key in ("ssh_host", "ssh_config", "scheduler")) else "local"
    if kind not in {"local", "remote"}:
        raise ComputeConfigurationError(f"profiles.{name}.kind must be local or remote")
    software_raw = _mapping(raw.get("software"), f"profiles.{name}.software")
    software = {
        backend: _software(backend, _mapping(value, f"profiles.{name}.software.{backend}"), kind)
        for backend, value in software_raw.items()
    }
    remote = None
    if kind == "remote":
        try:
            remote = parse_remote_profile(name, raw, base)
        except RemoteConfigurationError as exc:
            raise ComputeConfigurationError(str(exc)) from exc
        # RemoteProfile has the authoritative normalized software values.  It
        # also validates queue and scheduler constraints.
        software = {
            backend: SoftwareProvider(
                command=value.command,
                activation_script=value.activation_script,
                scratch_root=value.scratch_root,
                environment=dict(value.environment),
            )
            for backend, value in remote.software.items()
        }
    return ComputeProfile(name=name, kind=kind, software=software, remote=remote)


def _software(name: str, raw: dict[str, Any], kind: str) -> SoftwareProvider:
    command = raw.get("command")
    if kind == "local":
        if not isinstance(command, str) or not command.strip() or any(ord(char) < 32 for char in command):
            raise ComputeConfigurationError(f"software.{name}.command must be a non-empty string")
        normalized = (command.strip(),)
    else:
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ComputeConfigurationError(f"software.{name}.command must be a non-empty string array")
        normalized = tuple(command)
    activation = _optional_path(raw.get("activation_script"), f"software.{name}.activation_script", kind)
    scratch = _optional_path(raw.get("scratch_root"), f"software.{name}.scratch_root", kind)
    environment_raw = _mapping(raw.get("environment"), f"software.{name}.environment")
    environment: dict[str, str] = {}
    for key, value in environment_raw.items():
        if not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\x00" in value:
            raise ComputeConfigurationError(f"software.{name}.environment contains an invalid entry")
        environment[key] = value
    return SoftwareProvider(normalized, activation, scratch, environment)


def _optional_path(value: Any, label: str, kind: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ComputeConfigurationError(f"{label} must be a path string")
    if kind == "local":
        path = Path(value).expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
            raise ComputeConfigurationError(f"{label} must be an absolute readable regular file")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ComputeConfigurationError(f"{label} must be a TOML table")
    return value
