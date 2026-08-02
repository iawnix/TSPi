"""Validated domain models that do not depend on the MCP SDK."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import SecurityError

_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\[\]-]{0,127}$")
_MEMORY = re.compile(r"^[1-9][0-9]*(?:kb|mb|gb|tb)$", re.IGNORECASE)
_WALLTIME = re.compile(r"^(?P<hours>[0-9]{1,4}):(?P<minutes>[0-5][0-9]):(?P<seconds>[0-5][0-9])$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_PLACES = frozenset({"free", "pack", "scatter", "excl", "shared"})


def validate_job_id(job_id: str) -> str:
    value = job_id.strip()
    if not _JOB_ID.fullmatch(value):
        raise SecurityError("Invalid PBS job identifier")
    return value


def validate_job_name(name: str) -> str:
    value = name.strip()
    if not _JOB_NAME.fullmatch(value):
        raise SecurityError(
            "Job name must start with an alphanumeric character and contain only "
            "letters, digits, dot, underscore, or hyphen (maximum 63 characters)"
        )
    return value


def validate_walltime(value: str) -> str:
    match = _WALLTIME.fullmatch(value)
    if not match:
        raise SecurityError("walltime must use HH:MM:SS")
    if (
        int(match.group("hours")) == 0
        and int(match.group("minutes")) == 0
        and int(match.group("seconds")) == 0
    ):
        raise SecurityError("walltime must be greater than zero")
    return value


def validate_environment(environment: dict[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (environment or {}).items():
        if not _ENV_NAME.fullmatch(key):
            raise SecurityError(f"Invalid environment variable name: {key!r}")
        if (
            key.startswith("PBS_")
            or key.startswith("CLUSTER_MCP_")
            or key == "CUDA_VISIBLE_DEVICES"
        ):
            raise SecurityError(f"Environment variable {key!r} is reserved by PBS or cluster-mcp")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise SecurityError(
                f"Environment variable {key!r} contains a forbidden control character"
            )
        if len(value) > 16_384:
            raise SecurityError(f"Environment variable {key!r} is too large")
        result[key] = value
    return result


def validate_arguments(arguments: list[str]) -> list[str]:
    if len(arguments) > 512:
        raise SecurityError("A software invocation may contain at most 512 arguments")
    result: list[str] = []
    total = 0
    for argument in arguments:
        if not isinstance(argument, str):
            raise SecurityError("Every software argument must be a string")
        if "\x00" in argument or "\n" in argument or "\r" in argument:
            raise SecurityError("Software arguments may not contain NUL or newline characters")
        total += len(argument)
        if len(argument) > 16_384 or total > 131_072:
            raise SecurityError("Software arguments exceed the configured safety limit")
        result.append(argument)
    return result


@dataclass(frozen=True)
class ResourceRequest:
    """A conservative single- or multi-node PBS resource request."""

    nodes: int = 1
    ncpus: int = 1
    memory: str = "4gb"
    walltime: str = "01:00:00"
    ngpus: int = 0
    mpiprocs: int | None = None
    ompthreads: int | None = None
    host: str | None = None
    place: str | None = None

    def validate(self, *, max_nodes: int) -> ResourceRequest:
        if not 1 <= self.nodes <= max_nodes:
            raise SecurityError(f"nodes must be between 1 and {max_nodes}")
        if not 1 <= self.ncpus <= 4096:
            raise SecurityError("ncpus must be between 1 and 4096 per node")
        if not 0 <= self.ngpus <= 64:
            raise SecurityError("ngpus must be between 0 and 64 per node")
        if not _MEMORY.fullmatch(self.memory):
            raise SecurityError("memory must look like 4gb, 512mb, or 1tb")
        validate_walltime(self.walltime)
        for field_name, value in (("mpiprocs", self.mpiprocs), ("ompthreads", self.ompthreads)):
            if value is not None and not 1 <= value <= self.ncpus:
                raise SecurityError(f"{field_name} must be between 1 and ncpus")
        if self.host is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}", self.host
        ):
            raise SecurityError("host contains unsupported characters")
        if self.place is not None and self.place not in _SAFE_PLACES:
            raise SecurityError(f"place must be one of: {', '.join(sorted(_SAFE_PLACES))}")
        return self

    def select_value(self) -> str:
        chunks = [f"select={self.nodes}", f"ncpus={self.ncpus}"]
        if self.mpiprocs is not None:
            chunks.append(f"mpiprocs={self.mpiprocs}")
        if self.ompthreads is not None:
            chunks.append(f"ompthreads={self.ompthreads}")
        if self.ngpus:
            chunks.append(f"ngpus={self.ngpus}")
        chunks.append(f"mem={self.memory.lower()}")
        if self.host:
            chunks.append(f"host={self.host}")
        return ":".join(chunks)


@dataclass(frozen=True)
class JobSubmission:
    name: str
    queue: str
    workdir: str
    resources: ResourceRequest
    body_lines: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict)
    gpu_devices: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
