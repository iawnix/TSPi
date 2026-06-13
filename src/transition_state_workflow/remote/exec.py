"""Subprocess-based remote execution helpers.

The local side always uses argv-based subprocess calls. Shell syntax is allowed
only inside the explicitly selected remote shell on the final target host.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess

from transition_state_workflow.util.cli import (
    emit_captured_streams,
    emit_stdout,
)


def command_text(argv: list[str]) -> str:
    """Render argv as a copy-pasteable shell command for logging."""

    return " ".join(shlex.quote(part) for part in argv)


def print_captured_streams(label: str, stdout: str | None, stderr: str | None) -> None:
    """Write captured command output to stderr for actionable failures."""

    emit_captured_streams(label, stdout, stderr)


def bash_lc_command(command: str) -> str:
    """Return a remote command string that runs command inside bash -lc."""

    return command_text(["bash", "-lc", command])


@dataclass(frozen=True)
class RemoteTarget:
    """Remote SSH target with an optional compute host behind a login host."""

    login_host: str
    compute_host: str | None = None
    ssh_config: Path | None = None


class OpenSSHRemoteExecutor:
    """Remote executor backed by OpenSSH and subprocess.run(shell=False)."""

    def __init__(self, target: RemoteTarget, *, dry_run: bool = False) -> None:
        self.target = target
        self.dry_run = dry_run

    def ssh_prefix(self) -> list[str]:
        prefix = ["ssh"]
        if self.target.ssh_config:
            prefix.extend(["-F", str(self.target.ssh_config)])
        return prefix

    def scp_prefix(self) -> list[str]:
        prefix = ["scp"]
        if self.target.ssh_config:
            prefix.extend(["-F", str(self.target.ssh_config)])
        return prefix

    def login_argv(self, command: str) -> list[str]:
        """Build argv for a command interpreted only by the login host shell."""

        return [*self.ssh_prefix(), self.target.login_host, bash_lc_command(command)]

    def compute_argv(self, command: str) -> list[str]:
        """Build argv for a command interpreted only by the compute host shell.

        The inner compute command is itself a single shell-quoted login-host
        command. This prevents operators in ``command`` such as ``&&``, ``>``,
        ``&``, and ``$!`` from being interpreted by the login host shell.
        """

        if not self.target.compute_host:
            return self.login_argv(command)
        inner = command_text(["ssh", self.target.compute_host, "--", bash_lc_command(command)])
        return [*self.ssh_prefix(), self.target.login_host, inner]

    def run_argv(
        self,
        argv: list[str],
        *,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run argv locally without a shell, optionally capturing output."""

        emit_stdout(command_text(argv))
        if self.dry_run:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.run(argv, check=True, text=True, capture_output=capture_output)

    def run_login(self, command: str, *, label: str = "login command") -> subprocess.CompletedProcess[str]:
        """Run a shell snippet on the login host."""

        try:
            return self.run_argv(self.login_argv(command), capture_output=True)
        except subprocess.CalledProcessError as exc:
            print_captured_streams(label, exc.stdout, exc.stderr)
            raise

    def run_compute(self, command: str, *, label: str = "compute command") -> subprocess.CompletedProcess[str]:
        """Run a shell snippet on the compute host through the login host."""

        try:
            return self.run_argv(self.compute_argv(command), capture_output=True)
        except subprocess.CalledProcessError as exc:
            print_captured_streams(label, exc.stdout, exc.stderr)
            raise

    def put_to_login(self, local_path: Path, remote_path: str) -> subprocess.CompletedProcess[str]:
        """Upload a file to the login host with scp."""

        return self.run_argv(
            [*self.scp_prefix(), str(local_path), f"{self.target.login_host}:{remote_path}"],
            capture_output=False,
        )

    def get_from_login(self, remote_path: str, local_path: Path) -> subprocess.CompletedProcess[str]:
        """Download a file from the login host with scp."""

        return self.run_argv(
            [*self.scp_prefix(), f"{self.target.login_host}:{remote_path}", str(local_path)],
            capture_output=False,
        )
