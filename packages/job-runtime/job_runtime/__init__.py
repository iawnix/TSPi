"""Domain agnostic durable job execution primitives.

The package deliberately knows nothing about scientific programs, parsers, or
provider registries.  A job is a command plus declared inputs and outputs.
Interpretation of those outputs belongs to the caller (usually a Skill).
"""

from .models import (
    JobOutput,
    JobReceipt,
    JobSpec,
    JobState,
    JobStatus,
)
from .platform import ExecutionPlatform
from .local import LocalProcessPlatform
from .runtime import JobRuntime

__all__ = [
    "ExecutionPlatform", "JobOutput", "JobReceipt", "JobRuntime", "JobSpec",
    "JobState", "JobStatus", "LocalProcessPlatform",
]
