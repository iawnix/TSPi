"""Backend contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackendTask:
    act_id: str
    task_type: str
    work_dir: str
    inputs: dict[str, str]
    settings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedTask:
    backend: str
    act_id: str
    command: list[str]
    input_paths: list[str]
    expected_artifacts: list[str]
    environment: dict[str, str] = field(default_factory=dict)


class Backend(ABC):
    """Calculation adapter boundary."""

    name: str

    @abstractmethod
    def prepare(self, task: BackendTask) -> PreparedTask:
        """Return ResearchAct-scoped metadata without mutating canonical state."""
