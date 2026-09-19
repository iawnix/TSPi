"""Backend contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ts_agent.platforms import EnvironmentConfigurationError, load_config


@dataclass(frozen=True)
class BackendTask:
    node_id: str
    task_type: str
    work_dir: str
    inputs: dict[str, str]
    settings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedTask:
    backend: str
    node_id: str
    command: list[str]
    input_paths: list[str]
    expected_artifacts: list[str]
    environment: dict[str, str] = field(default_factory=dict)
    activation_script: str | None = None


class Backend(ABC):
    """Calculation adapter boundary."""

    name: str

    @abstractmethod
    def prepare(self, task: BackendTask) -> PreparedTask:
        """Return ResearchNode-scoped metadata without mutating canonical state."""


def configured_backend_command(backend_name: str) -> str:
    """Resolve one executable from the selected local compute environment."""

    try:
        config = load_config()
        environment = config.environment(kind="local")
        backend = environment.backends.get(backend_name)
    except EnvironmentConfigurationError:
        raise
    if backend is None or not backend.command:
        raise EnvironmentConfigurationError(
            f"local compute environment {environment.name!r} does not configure backend.{backend_name}"
        )
    return backend.command[0]


__all__ = ["Backend", "BackendTask", "PreparedTask", "configured_backend_command"]
