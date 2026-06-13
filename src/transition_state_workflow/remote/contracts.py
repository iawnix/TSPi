"""Transport-neutral remote execution and synchronization contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class RemoteWorkspace:
    """One remote calculation workspace and its local read-only mirror."""

    workspace_id: str
    remote_root: str
    local_mirror: Path


@dataclass(frozen=True)
class RemoteCommandResult:
    """Transport-neutral result of one remote argv execution."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SyncEntry:
    """One explicit remote-to-local synchronization item."""

    remote_path: str
    local_path: Path
    required: bool = True


@dataclass(frozen=True)
class SyncPlan:
    """Auditable synchronization plan for one remote workspace."""

    workspace: RemoteWorkspace
    entries: tuple[SyncEntry, ...]


class RemoteTransport(Protocol):
    """Execution and transfer boundary implemented by SSH, SFTP, or MCP."""

    def run(self, argv: Sequence[str], *, cwd: str | None = None) -> RemoteCommandResult:
        """Run argv remotely without exposing transport details to callers."""

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload one file."""

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download one file."""
