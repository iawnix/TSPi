"""Stable command result contract for future unified CLI routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from transition_state_workflow.util.cli import CLIBase, CLIResult


@dataclass(frozen=True)
class CommandResult:
    """Machine-readable result shared by command adapters."""

    ok: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()


class Command(Protocol):
    """One CLI command implementation independent of argument parsing."""

    name: str

    def run(self, argv: Sequence[str]) -> CommandResult:
        """Execute the command and return a stable result envelope."""
