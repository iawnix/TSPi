"""Bounded, argv-only subprocess execution."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import SchedulerError


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, *, timeout_seconds: int, max_output_bytes: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def _environment(self) -> dict[str, str]:
        allowed = (
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "KRB5CCNAME",
            "PBS_DEFAULT",
            "PBS_SERVER",
        )
        result = {key: os.environ[key] for key in allowed if key in os.environ}
        result["PATH"] = "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin"
        result.setdefault("LANG", "C.UTF-8")
        return result

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> CommandResult:
        if not argv or not all(
            isinstance(part, str) and part and "\x00" not in part for part in argv
        ):
            raise SchedulerError("Invalid scheduler command arguments")
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SchedulerError(f"Scheduler command not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SchedulerError(
                f"Scheduler command timed out after {self.timeout_seconds}s"
            ) from exc

        combined_size = len(completed.stdout) + len(completed.stderr)
        if combined_size > self.max_output_bytes:
            raise SchedulerError(
                f"Scheduler command output exceeded {self.max_output_bytes} bytes and was discarded"
            )
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        result = CommandResult(tuple(argv), completed.returncode, stdout, stderr)
        if check and completed.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"exit status {completed.returncode}"
            raise SchedulerError(f"Scheduler command failed: {detail[:2000]}")
        return result
