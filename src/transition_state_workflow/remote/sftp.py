"""Paramiko-backed SSH/SFTP transport adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from transition_state_workflow.remote.contracts import RemoteCommandResult
from transition_state_workflow.remote.exec import command_text


class ParamikoSFTPTransport:
    """Remote command and file-transfer adapter backed by Paramiko."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def from_host(
        cls,
        hostname: str,
        *,
        username: str | None = None,
        port: int = 22,
        key_filename: str | None = None,
        timeout: float | None = None,
        look_for_keys: bool = True,
    ) -> "ParamikoSFTPTransport":
        """Create a Paramiko SSH client only when Paramiko is available."""

        try:
            import paramiko  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("ParamikoSFTPTransport requires the optional 'paramiko' package") from exc

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=hostname,
            port=port,
            username=username,
            key_filename=key_filename,
            timeout=timeout,
            look_for_keys=look_for_keys,
        )
        return cls(client)

    def run(self, argv: Sequence[str], *, cwd: str | None = None) -> RemoteCommandResult:
        """Run argv through Paramiko's SSH channel."""

        command = command_text(list(argv))
        if cwd:
            command = f"cd {command_text([cwd])} && {command}"
        _stdin, stdout, stderr = self.client.exec_command(command)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        return RemoteCommandResult(returncode=status, stdout=stdout_text, stderr=stderr_text)

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload one file through SFTP."""

        sftp = self.client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download one file through SFTP."""

        local_path.parent.mkdir(parents=True, exist_ok=True)
        sftp = self.client.open_sftp()
        try:
            sftp.get(remote_path, str(local_path))
        finally:
            sftp.close()

    def close(self) -> None:
        """Close the underlying SSH client."""

        self.client.close()
