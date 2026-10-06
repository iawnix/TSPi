from __future__ import annotations

from typing import Any, Mapping

from .models import JobReceipt, JobSpec, JobStatus
from .platform import ExecutionPlatform


class JobRuntime:
    """Small dispatcher; platform adapters own execution details."""

    def __init__(self, platforms: Mapping[str, ExecutionPlatform], default: str = "local") -> None:
        if default not in platforms:
            raise ValueError(f"unknown default execution platform: {default}")
        self.platforms = dict(platforms)
        self.default = default

    def _platform(self, name: str | None) -> ExecutionPlatform:
        key = name or self.default
        try:
            return self.platforms[key]
        except KeyError as exc:
            raise ValueError(f"unknown execution platform: {key}") from exc

    def probe(self, spec: JobSpec, *, platform: str | None = None) -> dict[str, Any]:
        return self._platform(platform).probe(spec)

    def start(self, spec: JobSpec, *, platform: str | None = None) -> JobReceipt:
        return self._platform(platform).start(spec)

    # Tool-facing names.  They intentionally use the new ``job_*`` vocabulary
    # and have no compute/provider aliases.
    def job_start(self, spec: JobSpec, *, platform: str | None = None) -> JobReceipt:
        return self.start(spec, platform=platform)

    def status(self, receipt: JobReceipt) -> JobStatus:
        return self._platform(receipt.platform).status(receipt)

    def job_status(self, receipt: JobReceipt) -> JobStatus:
        return self.status(receipt)

    def collect(self, receipt: JobReceipt) -> dict[str, Any]:
        return self._platform(receipt.platform).collect(receipt)

    def job_collect(self, receipt: JobReceipt) -> dict[str, Any]:
        return self.collect(receipt)

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        return self._platform(receipt.platform).cancel(receipt)

    def job_cancel(self, receipt: JobReceipt) -> JobStatus:
        return self.cancel(receipt)

    def reconcile(self, receipt: JobReceipt) -> JobStatus:
        return self._platform(receipt.platform).reconcile(receipt)

    def job_reconcile(self, receipt: JobReceipt) -> JobStatus:
        return self.reconcile(receipt)

    def receipt_from_disk(self, path: str) -> JobReceipt:
        """Load a durable receipt and reconcile it through its platform."""
        # Receipt loading is platform-specific because remote adapters may use
        # a scheduler receipt format.  Local receipts are intentionally the
        # only generic format in this package.
        local = self._platform("local")
        loader = getattr(local, "receipt_from_disk", None)
        if not callable(loader):
            raise TypeError("configured local platform cannot load durable receipts")
        return loader(path)

    def job_probe(self, spec: JobSpec, *, platform: str | None = None) -> dict[str, Any]:
        return self.probe(spec, platform=platform)
