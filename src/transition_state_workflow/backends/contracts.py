"""Backend-neutral input and output contracts for chemistry programs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class BackendInput:
    """Prepared backend input artifacts and execution metadata."""

    backend: str
    files: tuple[Path, ...]
    command_argv: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendOutput:
    """Parsed backend output without workflow-state decisions."""

    backend: str
    artifacts: tuple[Path, ...]
    properties: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()


class BackendAdapter(Protocol):
    """Prepare and parse one program without planning or finalizing nodes."""

    name: str

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Prepare program-specific inputs from a backend-neutral request."""

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Parse program output into backend-neutral properties."""
