"""Backend contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ts_agent.compute.config import ComputeConfigurationError, load_config


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


def configured_backend_command(provider: str, _default: str | None = None) -> str:
    """Resolve one executable from the selected local compute profile.

    The second argument is accepted only for call-site readability during the
    backend transition; no default executable is used when configuration is
    absent or incomplete.
    """

    try:
        config = load_config()
        profile = config.profile(kind="local")
        software = profile.software.get(provider)
    except ComputeConfigurationError:
        raise
    if software is None or not software.command:
        raise ComputeConfigurationError(
            f"local compute profile {profile.name!r} does not configure software.{provider}"
        )
    return software.command[0]


__all__ = ["Backend", "BackendTask", "PreparedTask", "configured_backend_command"]
