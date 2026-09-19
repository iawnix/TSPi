"""Thin OpenSSH/SCP client for a remote compute platform."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import RemoteCommandError
from .models import RemotePlatform


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


class SSHClient:
    def __init__(self, platform: RemotePlatform, *, runner: Runner = subprocess.run) -> None:
        self.platform = platform.validate()
        self._runner = runner

    def run(
        self,
        remote_argv: list[str] | tuple[str, ...],
        *,
        check: bool = True,
        input_text: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        if not remote_argv or any("\x00" in str(item) for item in remote_argv):
            raise ValueError("remote argv must contain non-empty NUL-free arguments")
        remote_command = shlex.join([str(item) for item in remote_argv])
        argv = [*self._ssh_prefix(), self.platform.ssh_host, remote_command]
        return self._execute(argv, "SSH command failed", check, input_text, timeout)

    def run_script(
        self,
        script: str,
        args: list[str] | tuple[str, ...] = (),
        *,
        check: bool = True,
        timeout: int | None = None,
    ) -> CommandResult:
        remote_command = "bash -s --"
        if args:
            remote_command += " " + shlex.join([str(item) for item in args])
        argv = [*self._ssh_prefix(), self.platform.ssh_host, remote_command]
        return self._execute(argv, "remote script failed", check, script, timeout)

    def upload(self, source: Path, remote_path: str) -> CommandResult:
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"upload source is not a regular file: {source}")
        argv = [*self._scp_prefix(), str(source), f"{self.platform.ssh_host}:{remote_path}"]
        return self._execute(argv, "SCP upload failed", True, None, None)

    def download(self, remote_path: str, destination: Path) -> CommandResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        argv = [*self._scp_prefix(), f"{self.platform.ssh_host}:{remote_path}", str(destination)]
        return self._execute(argv, "SCP download failed", True, None, None)

    def read_text(self, remote_path: str, *, check: bool = True, max_bytes: int = 1024 * 1024) -> str:
        result = self.run(
            ["head", "-c", str(max_bytes), "--", remote_path],
            check=check,
        )
        return result.stdout

    def _execute(
        self,
        argv: list[str],
        label: str,
        check: bool,
        input_text: str | None,
        timeout: int | None,
    ) -> CommandResult:
        completed = self._runner(
            argv,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout or self.platform.command_timeout_seconds,
        )
        result = CommandResult(tuple(argv), completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            raise RemoteCommandError(
                label,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def _ssh_prefix(self) -> list[str]:
        return [
            "ssh",
            "-F",
            str(self.platform.ssh_config),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.platform.connect_timeout_seconds}",
            "--",
        ]

    def _scp_prefix(self) -> list[str]:
        return [
            "scp",
            "-F",
            str(self.platform.ssh_config),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.platform.connect_timeout_seconds}",
            "--",
        ]
