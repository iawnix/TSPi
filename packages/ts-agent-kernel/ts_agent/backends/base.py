"""Backend contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class BackendTask:
    node_id: str
    task_type: str
    work_dir: str
    inputs: dict[str, str]
    settings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedTask:
    backend: str
    node_id: str
    command: list[str]
    input_paths: list[str]
    expected_artifacts: list[str]
    environment: dict[str, str] = field(default_factory=dict)
    activation_script: str | None = None


class Backend(ABC):
    """Calculation adapter boundary."""

    name: str

    @abstractmethod
    def prepare(self, task: BackendTask) -> PreparedTask:
        """Return ResearchNode-scoped metadata without mutating canonical state."""


@dataclass(frozen=True)
class ConfiguredBackend:
    command: str
    activation_script: str | None = None


def configured_backend(name: str, default: str) -> ConfiguredBackend:
    """Resolve an optional installation-owned local backend executable."""
    compute_configured = os.environ.get("TS_COMPUTE_CONFIG", "").strip()
    if not compute_configured:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            compute_configured = str(Path(install_root) / ".pi" / "compute.toml")
    if compute_configured:
        value = _configured_from_compute(Path(compute_configured).expanduser(), name, default)
        if value is not None:
            return value
    configured = os.environ.get("TS_LOCAL_CONFIG", "").strip()
    if not configured:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            configured = str(Path(install_root) / ".pi" / "local.toml")
    if not configured:
        return ConfiguredBackend(command=default)
    path = Path(configured).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return ConfiguredBackend(command=default)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ConfiguredBackend(command=default)
    table = raw.get("backends", raw.get("local", raw))
    if not isinstance(table, dict):
        return ConfiguredBackend(command=default)
    value = table.get(name, default)
    activation = None
    if isinstance(value, dict):
        value = value.get("command", default)
        activation_value = table[name].get("activation_script")
        if isinstance(activation_value, str) and activation_value.strip():
            activation_path = Path(activation_value).expanduser()
            if (
                activation_path.is_absolute()
                and not activation_path.is_symlink()
                and activation_path.is_file()
                and os.access(activation_path, os.R_OK)
            ):
                activation = str(activation_path)
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        return ConfiguredBackend(command=default)
    return ConfiguredBackend(command=value.strip(), activation_script=activation)


def _configured_from_compute(path: Path, name: str, default: str) -> ConfiguredBackend | None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return None
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles")
        if not isinstance(profiles, dict):
            return None
        selected = os.environ.get("TS_COMPUTE_PROFILE", "").strip() or raw.get("default_profile")
        profile = profiles.get(selected)
        if not isinstance(profile, dict) or profile.get("kind") != "local":
            return None
        table = profile.get("software")
        value = table.get(name) if isinstance(table, dict) else None
        if not isinstance(value, dict):
            return None
        command = value.get("command")
        if not isinstance(command, str) or not command.strip() or any(ord(char) < 32 for char in command):
            return None
        activation = value.get("activation_script")
        activation_path = Path(activation).expanduser() if isinstance(activation, str) and activation.strip() else None
        if activation_path is not None and (
            not activation_path.is_absolute()
            or activation_path.is_symlink()
            or not activation_path.is_file()
            or not os.access(activation_path, os.R_OK)
        ):
            activation_path = None
        return ConfiguredBackend(
            command=command.strip(),
            activation_script=str(activation_path) if activation_path is not None else None,
        )
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def configured_backend_command(name: str, default: str) -> str:
    return configured_backend(name, default).command


def configured_backend_activation(name: str) -> str | None:
    return configured_backend(name, "").activation_script
