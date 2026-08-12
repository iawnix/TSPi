"""Typed contracts for one installation-owned remote scheduler."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import RemoteConfigurationError


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_QUEUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MEMORY = re.compile(r"^[1-9][0-9]*(?:kb|mb|gb|tb)$")
_WALLTIME = re.compile(r"^[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]$")
_REMOTE_PATH_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class SchedulerCommands:
    qsub: str = "/opt/torque/bin/qsub"
    qstat: str = "/opt/torque/bin/qstat"
    qdel: str = "/opt/torque/bin/qdel"
    pbsnodes: str = "/opt/torque/bin/pbsnodes"


@dataclass(frozen=True)
class SoftwareProfile:
    command: tuple[str, ...]
    activation_script: str | None = None
    allowed_queues: tuple[str, ...] = ()
    requires_gpu: bool = False
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteProfile:
    name: str
    ssh_host: str
    ssh_config: Path
    scheduler: str
    remote_root: str
    allowed_queues: tuple[str, ...]
    max_nodes: int
    connect_timeout_seconds: int
    command_timeout_seconds: int
    commands: SchedulerCommands
    software: dict[str, SoftwareProfile]

    def validate(self) -> "RemoteProfile":
        if not _NAME.fullmatch(self.name):
            raise RemoteConfigurationError(f"invalid remote profile name: {self.name!r}")
        if not self.ssh_host or any(character.isspace() for character in self.ssh_host):
            raise RemoteConfigurationError(f"invalid ssh_host for profile {self.name}")
        if not self.ssh_config.is_absolute() or not self.ssh_config.is_file():
            raise RemoteConfigurationError(
                f"ssh_config is not an absolute readable file for profile {self.name}: {self.ssh_config}"
            )
        if self.scheduler != "torque":
            raise RemoteConfigurationError("ts_remote currently supports scheduler=torque only")
        validate_remote_path(self.remote_root, label="remote_root")
        if not self.allowed_queues or any(not _QUEUE.fullmatch(item) for item in self.allowed_queues):
            raise RemoteConfigurationError(f"profile {self.name} has an invalid queue allowlist")
        if self.max_nodes < 1:
            raise RemoteConfigurationError("max_nodes must be positive")
        if not 1 <= self.connect_timeout_seconds <= 300:
            raise RemoteConfigurationError("connect_timeout_seconds must be between 1 and 300")
        if not 1 <= self.command_timeout_seconds <= 3600:
            raise RemoteConfigurationError("command_timeout_seconds must be between 1 and 3600")
        for backend, software in self.software.items():
            if not _NAME.fullmatch(backend) or not software.command:
                raise RemoteConfigurationError(f"invalid software profile: {backend!r}")
            if software.activation_script is not None:
                validate_remote_path(software.activation_script, label=f"software.{backend}.activation_script")
            if software.allowed_queues and not set(software.allowed_queues).issubset(self.allowed_queues):
                raise RemoteConfigurationError(
                    f"software.{backend}.allowed_queues must be a subset of profile queues"
                )
        return self


@dataclass(frozen=True)
class RemoteResources:
    queue: str
    nodes: int
    ncpus: int
    memory: str
    walltime: str
    ngpus: int = 0
    mpiprocs: int | None = None
    ompthreads: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RemoteResources":
        try:
            resources = cls(
                queue=str(value["queue"]),
                nodes=int(value["nodes"]),
                ncpus=int(value["ncpus"]),
                memory=str(value["memory"]).lower(),
                walltime=str(value["walltime"]),
                ngpus=int(value.get("ngpus", 0)),
                mpiprocs=_optional_int(value.get("mpiprocs")),
                ompthreads=_optional_int(value.get("ompthreads")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteConfigurationError("remote resources are incomplete or invalid") from exc
        return resources.validate()

    def validate(self) -> "RemoteResources":
        if not _QUEUE.fullmatch(self.queue):
            raise RemoteConfigurationError(f"invalid queue name: {self.queue!r}")
        if self.nodes < 1 or self.ncpus < 1 or self.ngpus < 0:
            raise RemoteConfigurationError("nodes/ncpus must be positive and ngpus non-negative")
        if self.mpiprocs is not None and self.mpiprocs < 1:
            raise RemoteConfigurationError("mpiprocs must be positive")
        if self.ompthreads is not None and self.ompthreads < 1:
            raise RemoteConfigurationError("ompthreads must be positive")
        if not _MEMORY.fullmatch(self.memory):
            raise RemoteConfigurationError(f"invalid memory request: {self.memory!r}")
        if not _WALLTIME.fullmatch(self.walltime):
            raise RemoteConfigurationError(f"invalid walltime request: {self.walltime!r}")
        return self


@dataclass(frozen=True)
class RemoteJobConfig:
    submission_id: str
    intent_id: str
    intent_digest: str
    node_id: str
    backend: str
    profile: RemoteProfile
    remote_dir: str
    resources: RemoteResources
    command: tuple[str, ...]
    input_paths: tuple[Path, ...]
    expected_artifacts: tuple[str, ...]
    output_dir: Path
    environment: dict[str, str] = field(default_factory=dict)
    stdout_name: str = "remote_job.stdout"
    stderr_name: str = "remote_job.stderr"
    script_name: str = "job.pbs"
    program_status_name: str = "program_status.json"


@dataclass(frozen=True)
class RemoteReceipt:
    schema_version: str
    submission_id: str
    intent_id: str
    intent_digest: str
    node_id: str
    profile: str
    scheduler: str
    scheduler_id: str
    remote_dir: str
    script_sha256: str
    submitted_at: str
    expected_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class RemoteJobStatus:
    state: str
    program_status: str
    job_id: str
    scheduler_state: str | None = None
    exit_status: int | None = None
    error_class: str | None = None
    scheduler_query_error: str | None = None
    program_record: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransferRecord:
    remote_path: str
    size: int
    sha256: str


def validate_remote_path(value: str, *, label: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or str(path) == "/" or ".." in path.parts:
        raise RemoteConfigurationError(f"{label} must be a non-root absolute POSIX path")
    if any(part and not _REMOTE_PATH_PART.fullmatch(part) for part in path.parts[1:]):
        raise RemoteConfigurationError(f"{label} contains unsupported path characters: {value}")
    return str(path)


def validate_artifact_name(value: str) -> str:
    if not value or value != PurePosixPath(value).name or not _REMOTE_PATH_PART.fullmatch(value):
        raise RemoteConfigurationError(f"invalid remote artifact basename: {value!r}")
    return value


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
