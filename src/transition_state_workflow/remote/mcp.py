"""MCP-backed remote transport adapter boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Sequence

from transition_state_workflow.remote.contracts import RemoteCommandResult

RunCommand = Callable[[Sequence[str], str | None], Mapping[str, Any] | RemoteCommandResult]
UploadFile = Callable[[Path, str], None]
DownloadFile = Callable[[str, Path], None]


class MCPTransport:
    """Remote transport adapter around injected MCP command/file tools."""

    def __init__(
        self,
        *,
        run_command: RunCommand,
        upload_file: UploadFile,
        download_file: DownloadFile,
    ) -> None:
        self.run_command = run_command
        self.upload_file = upload_file
        self.download_file = download_file

    def run(self, argv: Sequence[str], *, cwd: str | None = None) -> RemoteCommandResult:
        """Run argv through the injected MCP command tool."""

        result = self.run_command(argv, cwd)
        if isinstance(result, RemoteCommandResult):
            return result
        return RemoteCommandResult(
            returncode=int(result.get("returncode", result.get("status", 0))),
            stdout=str(result.get("stdout", "")),
            stderr=str(result.get("stderr", "")),
        )

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload one file through the injected MCP file tool."""

        self.upload_file(local_path, remote_path)

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download one file through the injected MCP file tool."""

        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.download_file(remote_path, local_path)
