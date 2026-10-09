from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import JobReceipt, JobSpec, JobStatus


class ExecutionPlatform(ABC):
    """Execution adapter contract shared by local and remote platforms."""

    name: str

    @abstractmethod
    def probe(self, spec: JobSpec) -> dict[str, Any]:
        """Return observations needed before submission; never run the job."""

    @abstractmethod
    def start(self, spec: JobSpec) -> JobReceipt:
        """Stage and submit one job."""

    @abstractmethod
    def status(self, receipt: JobReceipt) -> JobStatus: ...

    @abstractmethod
    def collect(self, receipt: JobReceipt) -> dict[str, Any]: ...

    @abstractmethod
    def cancel(self, receipt: JobReceipt) -> JobStatus: ...

    def reconcile(self, receipt: JobReceipt) -> JobStatus:
        """Reconcile after a runtime restart; adapters may override."""
        return self.status(receipt)
