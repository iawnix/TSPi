"""Domain-neutral execution boundary for the research runtime.

This module is intentionally small.  It accepts an argv command and declared
files, then delegates lifecycle work to :mod:`job_runtime`.  Scientific
providers, parsers, capability descriptors, and readiness gates do not appear
in this API.  Skills can use it directly or expose it through Agent Server
tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from job_runtime import (
    JobOutput,
    JobReceipt,
    JobRuntime,
    JobSpec,
    JobStatus,
    LocalProcessPlatform,
)


@dataclass(frozen=True)
class ExecutionRequest:
    """A complete, reproducible request for one Job Attempt."""

    command: tuple[str, ...]
    cwd: Path
    workspace_id: str | None = None
    node_id: str | None = None
    attempt_id: str | None = None
    job_id: str | None = None
    inputs: tuple[Path, ...] = ()
    outputs: tuple[JobOutput, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_job_spec(self) -> JobSpec:
        return JobSpec(
            command=self.command,
            cwd=self.cwd,
            job_id=self.job_id,
            env=self.env,
            inputs=self.inputs,
            outputs=self.outputs,
            timeout_seconds=self.timeout_seconds,
            metadata=self.metadata,
            workspace_id=self.workspace_id,
            node_id=self.node_id,
            attempt_id=self.attempt_id,
        )


class ExecutionService:
    """Facade consumed by Agent Server's ``job_*`` tool handlers.

    A service instance owns no Research State and makes no scientific claims.
    Its only durable authority is the Job Runtime receipt/status under the
    attempt workspace.
    """

    def __init__(self, runtime: JobRuntime | None = None) -> None:
        self.runtime = runtime or JobRuntime({"local": LocalProcessPlatform()})

    def probe(self, request: ExecutionRequest, *, platform: str | None = None):
        return self.runtime.job_probe(request.to_job_spec(), platform=platform)

    def start(self, request: ExecutionRequest, *, platform: str | None = None) -> JobReceipt:
        return self.runtime.job_start(request.to_job_spec(), platform=platform)

    def status(self, receipt: JobReceipt) -> JobStatus:
        return self.runtime.job_status(receipt)

    def collect(self, receipt: JobReceipt):
        return self.runtime.job_collect(receipt)

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        return self.runtime.job_cancel(receipt)

    def reconcile(self, receipt: JobReceipt) -> JobStatus:
        return self.runtime.job_reconcile(receipt)

    def receipt_from_disk(self, path: str | Path) -> JobReceipt:
        return self.runtime.receipt_from_disk(str(path))


__all__ = ["ExecutionRequest", "ExecutionService"]
