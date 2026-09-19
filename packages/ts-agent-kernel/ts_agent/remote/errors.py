"""Errors raised by the deterministic remote-compute boundary."""

from __future__ import annotations


class RemoteError(RuntimeError):
    """Base error for platform, SSH, transfer, and scheduler failures."""


class RemoteConfigurationError(RemoteError):
    """The installation-owned remote platform is missing or invalid."""


class RemoteCommandError(RemoteError):
    """A bounded SSH or SCP command returned a non-zero status."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr.strip() or stdout.strip()
        suffix = f": {detail[:2000]}" if detail else ""
        super().__init__(f"{message} (exit {returncode}){suffix}")


class RemotePreSubmitError(RemoteError):
    """A staging failure occurred before qsub could be invoked."""

    def __init__(self, phase: str, cause: Exception) -> None:
        self.phase = phase
        self.cause = cause
        super().__init__(f"remote {phase} failed before scheduler submission: {cause}")


class RemoteSubmissionRejected(RemoteError):
    """qsub returned a durable rejection without a scheduler job ID."""

    def __init__(self, record: dict[str, object]) -> None:
        self.record = record
        detail = str(record.get("error") or "scheduler rejected the submission")
        super().__init__(detail)


class RemoteSubmissionAmbiguous(RemoteError):
    """qsub may have started, but no authoritative outcome is available."""

    def __init__(self, record: dict[str, object] | None = None) -> None:
        self.record = record or {}
        super().__init__("scheduler submission outcome is ambiguous; reconcile before retrying")


class RemoteCancellationAmbiguous(RemoteError):
    """qdel may have started, but its effect cannot be confirmed."""
