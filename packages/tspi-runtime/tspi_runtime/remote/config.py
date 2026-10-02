"""Parse the remote portion of one compute environment."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .errors import RemoteConfigurationError
from .models import RemoteBackendBinding, RemotePlatform, SchedulerCommands


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_environment(name: str, raw: dict[str, Any], base: Path) -> RemotePlatform:
    ssh_config_raw = _string(raw.get("ssh_config"), f"environments.{name}.ssh_config")
    ssh_config = Path(os.path.expandvars(os.path.expanduser(ssh_config_raw)))
    if not ssh_config.is_absolute():
        ssh_config = base / ssh_config
    commands_raw = _mapping(raw.get("commands"), f"environments.{name}.commands")
    commands = SchedulerCommands(
        qsub=_command(commands_raw.get("qsub", SchedulerCommands.qsub), "qsub"),
        qstat=_command(commands_raw.get("qstat", SchedulerCommands.qstat), "qstat"),
        qdel=_command(commands_raw.get("qdel", SchedulerCommands.qdel), "qdel"),
        pbsnodes=_command(commands_raw.get("pbsnodes", SchedulerCommands.pbsnodes), "pbsnodes"),
    )
    queues = _strings(raw.get("allowed_queues"), f"environments.{name}.allowed_queues")
    backends_raw = _mapping(raw.get("backends"), f"environments.{name}.backends")
    backends = {
        backend: _backend_binding(
            backend,
            _mapping(value, f"environments.{name}.backends.{backend}"),
            queues,
        )
        for backend, value in backends_raw.items()
    }
    return RemotePlatform(
        name=name,
        ssh_host=_string(raw.get("ssh_host"), f"environments.{name}.ssh_host"),
        ssh_config=ssh_config.resolve(strict=False),
        scheduler=_string(raw.get("scheduler", "torque"), f"environments.{name}.scheduler"),
        remote_root=_string(raw.get("remote_root"), f"environments.{name}.remote_root"),
        allowed_queues=queues,
        max_nodes=_positive_int(raw.get("max_nodes", 1), f"environments.{name}.max_nodes"),
        connect_timeout_seconds=_positive_int(
            raw.get("connect_timeout_seconds", 15),
            f"environments.{name}.connect_timeout_seconds",
        ),
        command_timeout_seconds=_positive_int(
            raw.get("command_timeout_seconds", 60),
            f"environments.{name}.command_timeout_seconds",
        ),
        commands=commands,
        backends=backends,
    ).validate()


def _backend_binding(
    name: str,
    raw: dict[str, Any],
    environment_queues: tuple[str, ...],
) -> RemoteBackendBinding:
    command = _strings(raw.get("command"), f"backends.{name}.command")
    activation = raw.get("activation_script")
    if activation is not None and (not isinstance(activation, str) or not activation):
        raise RemoteConfigurationError(f"backends.{name}.activation_script must be a path string")
    scratch_root = raw.get("scratch_root")
    if scratch_root is not None and (not isinstance(scratch_root, str) or not scratch_root):
        raise RemoteConfigurationError(f"backends.{name}.scratch_root must be a path string")
    allowed = _strings(
        raw.get("allowed_queues", list(environment_queues)),
        f"backends.{name}.allowed_queues",
    )
    requires_gpu = raw.get("requires_gpu", False)
    if not isinstance(requires_gpu, bool):
        raise RemoteConfigurationError(f"backends.{name}.requires_gpu must be true or false")
    environment_raw = _mapping(raw.get("environment"), f"backends.{name}.environment")
    environment: dict[str, str] = {}
    for key, value in environment_raw.items():
        if not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\x00" in value:
            raise RemoteConfigurationError(f"backends.{name}.environment contains an invalid entry")
        environment[key] = value
    return RemoteBackendBinding(
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
