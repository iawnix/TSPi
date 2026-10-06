"""Remote execution adapter contract.

Concrete SSH/scheduler implementations live outside the generic runtime.  The
adapter remains deliberately small so a remote platform has exactly the same
job lifecycle as the local process platform.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from .models import JobReceipt, JobSpec, JobStatus
from .platform import ExecutionPlatform


class RemoteExecutionPlatform(ExecutionPlatform):
    """Base class for SSH, Slurm, PBS/Torque, and container adapters."""

    name = "remote"

    @abstractmethod
    def stage_inputs(self, spec: JobSpec) -> dict[str, Any]: ...

    @abstractmethod
    def fetch_outputs(self, receipt: JobReceipt) -> dict[str, Any]: ...

