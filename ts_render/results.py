"""Structured render command results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    output_path: str | None
    command: list[str]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "output_path": self.output_path,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "diagnostics": self.diagnostics,
        }

    @classmethod
    def missing_command(cls, command_name: str, diagnostics: list[str] | None = None) -> "RenderResult":
        return cls(
            ok=False,
            output_path=None,
            command=[],
            returncode=None,
            stderr=f"{command_name} command is not available",
            diagnostics=diagnostics or [],
        )


def output_exists(path: str | Path | None) -> bool:
    return bool(path) and Path(path).exists()
