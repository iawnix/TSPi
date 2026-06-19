"""Backend contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackendTask:
    node_id: str
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
