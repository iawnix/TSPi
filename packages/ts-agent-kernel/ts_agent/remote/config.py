"""Load installation-owned ts_remote profiles from TOML."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RemoteConfigurationError
from .models import RemoteProfile, SchedulerCommands, SoftwareProfile


COMPUTE_CONFIG_ENV = "TS_COMPUTE_CONFIG"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RemoteConfig:
    source: Path
    default_profile: str
    profiles: dict[str, RemoteProfile]

    def profile(self, name: str) -> RemoteProfile:
        try:
            return self.profiles[name]
        except KeyError as exc:
            raise RemoteConfigurationError(f"unknown ts_remote profile: {name}") from exc


def configured_path() -> Path:
    raw = os.environ.get(COMPUTE_CONFIG_ENV, "").strip()
    if not raw:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        candidate = Path(install_root) / ".pi" / "compute.toml" if install_root else None
        if candidate is not None and candidate.is_file():
            raw = str(candidate)
    if not raw:
        raise RemoteConfigurationError(f"{COMPUTE_CONFIG_ENV} is not configured")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RemoteConfigurationError(f"{COMPUTE_CONFIG_ENV} must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise RemoteConfigurationError(f"{COMPUTE_CONFIG_ENV} is not a regular file: {path}")
    return path.resolve(strict=True)


def load_config(path: str | Path | None = None) -> RemoteConfig:
    source = Path(path).expanduser().resolve(strict=True) if path is not None else configured_path()
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    profiles_raw = _mapping(raw.get("profiles"), "profiles")
    if not profiles_raw:
        raise RemoteConfigurationError("ts_remote config must define at least one profile")
    profiles = {
        name: _profile(name, _mapping(value, f"profiles.{name}"), source.parent)
        for name, value in profiles_raw.items()
        if not (isinstance(value, dict) and value.get("kind") == "local")
    }
    default = raw.get("default_profile")
    if not isinstance(default, str) or default not in profiles:
        default = next(iter(profiles), None)
    if not isinstance(default, str) or default not in profiles:
        raise RemoteConfigurationError("default_profile must name one configured profile")
    return RemoteConfig(source=source, default_profile=default, profiles=profiles)


def _profile(name: str, raw: dict[str, Any], base: Path) -> RemoteProfile:
    ssh_config_raw = _string(raw.get("ssh_config"), f"profiles.{name}.ssh_config")
    ssh_config = Path(os.path.expandvars(os.path.expanduser(ssh_config_raw)))
    if not ssh_config.is_absolute():
        ssh_config = base / ssh_config
    commands_raw = _mapping(raw.get("commands"), f"profiles.{name}.commands")
    commands = SchedulerCommands(
        qsub=_command(commands_raw.get("qsub", SchedulerCommands.qsub), "qsub"),
        qstat=_command(commands_raw.get("qstat", SchedulerCommands.qstat), "qstat"),
        qdel=_command(commands_raw.get("qdel", SchedulerCommands.qdel), "qdel"),
        pbsnodes=_command(commands_raw.get("pbsnodes", SchedulerCommands.pbsnodes), "pbsnodes"),
    )
    queues = _strings(raw.get("allowed_queues"), f"profiles.{name}.allowed_queues")
    software_raw = _mapping(raw.get("software"), f"profiles.{name}.software")
    software = {
        backend: _software(backend, _mapping(value, f"profiles.{name}.software.{backend}"), queues)
        for backend, value in software_raw.items()
    }
    return RemoteProfile(
        name=name,
        ssh_host=_string(raw.get("ssh_host"), f"profiles.{name}.ssh_host"),
        ssh_config=ssh_config.resolve(strict=False),
        scheduler=_string(raw.get("scheduler", "torque"), f"profiles.{name}.scheduler"),
        remote_root=_string(raw.get("remote_root"), f"profiles.{name}.remote_root"),
        allowed_queues=queues,
        max_nodes=_positive_int(raw.get("max_nodes", 1), f"profiles.{name}.max_nodes"),
        connect_timeout_seconds=_positive_int(
            raw.get("connect_timeout_seconds", 15),
            f"profiles.{name}.connect_timeout_seconds",
        ),
        command_timeout_seconds=_positive_int(
            raw.get("command_timeout_seconds", 60),
            f"profiles.{name}.command_timeout_seconds",
        ),
        commands=commands,
        software=software,
    ).validate()


def parse_profile(name: str, raw: dict[str, Any], base: Path) -> RemoteProfile:
    """Parse one remote profile for the unified compute config loader."""
    return _profile(name, raw, base)


def _software(name: str, raw: dict[str, Any], profile_queues: tuple[str, ...]) -> SoftwareProfile:
    command = _strings(raw.get("command"), f"software.{name}.command")
    activation = raw.get("activation_script")
    if activation is not None and (not isinstance(activation, str) or not activation):
        raise RemoteConfigurationError(f"software.{name}.activation_script must be a path string")
    scratch_root = raw.get("scratch_root")
    if scratch_root is not None and (not isinstance(scratch_root, str) or not scratch_root):
        raise RemoteConfigurationError(f"software.{name}.scratch_root must be a path string")
    allowed = _strings(
        raw.get("allowed_queues", list(profile_queues)),
        f"software.{name}.allowed_queues",
    )
    requires_gpu = raw.get("requires_gpu", False)
    if not isinstance(requires_gpu, bool):
        raise RemoteConfigurationError(f"software.{name}.requires_gpu must be true or false")
    environment_raw = _mapping(raw.get("environment"), f"software.{name}.environment")
    environment: dict[str, str] = {}
    for key, value in environment_raw.items():
        if not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\x00" in value:
            raise RemoteConfigurationError(f"software.{name}.environment contains an invalid entry")
        environment[key] = value
    return SoftwareProfile(
        command=command,
        activation_script=activation,
        scratch_root=scratch_root,
        allowed_queues=allowed,
        requires_gpu=requires_gpu,
        environment=environment,
    )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RemoteConfigurationError(f"{label} must be a TOML table")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RemoteConfigurationError(f"{label} must be a non-empty string")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise RemoteConfigurationError(f"{label} must be a non-empty string array")
    return tuple(dict.fromkeys(value))


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RemoteConfigurationError(f"{label} must be a positive integer")
    return value


def _command(value: Any, label: str) -> str:
    command = _string(value, label)
    if any(character.isspace() for character in command):
        raise RemoteConfigurationError(f"scheduler command {label} cannot contain whitespace")
    return command
