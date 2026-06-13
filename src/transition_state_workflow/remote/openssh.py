"""OpenSSH-backed implementation of the RemoteTransport protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from transition_state_workflow.remote.contracts import RemoteCommandResult, RemoteTransport
from transition_state_workflow.util.remote_exec import OpenSSHRemoteExecutor, RemoteTarget, command_text


class OpenSSHTransport:
    """Transport adapter around the existing argv-only OpenSSH executor."""

    def __init__(self, executor: OpenSSHRemoteExecutor) -> None:
        self.executor = executor

    @classmethod
    def from_target(
        cls,
        login_host: str,
        *,
        compute_host: str | None = None,
        ssh_config: Path | None = None,
        dry_run: bool = False,
    ) -> "OpenSSHTransport":
        """Build a transport from host settings."""

        return cls(
            OpenSSHRemoteExecutor(
                RemoteTarget(login_host=login_host, compute_host=compute_host, ssh_config=ssh_config),
                dry_run=dry_run,
            )
        )

    def run(self, argv: Sequence[str], *, cwd: str | None = None) -> RemoteCommandResult:
        """Run argv on the selected remote target via the final remote shell."""

        command = command_text(list(argv))
        if cwd:
            command = f"cd {command_text([cwd])} && {command}"
        completed = self.executor.run_compute(command)
        return RemoteCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload one local file to the login host."""

        self.executor.put_to_login(local_path, remote_path)

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download one remote file from the login host."""

        self.executor.get_from_login(remote_path, local_path)


def assert_remote_transport(transport: RemoteTransport) -> RemoteTransport:
    """Return transport unchanged; useful for type and protocol tests."""

    return transport
