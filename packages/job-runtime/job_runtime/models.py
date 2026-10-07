from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class JobState(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    QUEUED = "queued"
    HELD = "held"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    COLLECTED = "collected"


@dataclass(frozen=True)
class JobOutput:
    """An output explicitly requested by the caller."""

    path: str
    required: bool = False
    media_type: str | None = None
    min_bytes: int = 0


@dataclass(frozen=True)
class JobSpec:
    command: tuple[str, ...]
    cwd: Path
    job_id: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    inputs: tuple[Path, ...] = ()
    outputs: tuple[JobOutput, ...] = ()
    stdin: Path | None = None
    timeout_seconds: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    workspace_id: str | None = None
    node_id: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(item, str) and item for item in self.command):
            raise ValueError("job command must contain at least one non-empty argument")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("job timeout_seconds must be positive")
        for output in self.outputs:
            if output.min_bytes < 0:
                raise ValueError("min_bytes must be nonnegative")
            path = Path(output.path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"job output path must stay below cwd: {output.path!r}")


@dataclass(frozen=True)
class JobReceipt:
    job_id: str
    platform: str
    submitted_at: str
    command: tuple[str, ...]
    cwd: str
    pid: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    workspace_id: str | None = None
    node_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: JobState
    platform: str
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    outputs: tuple[JobOutput, ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)
