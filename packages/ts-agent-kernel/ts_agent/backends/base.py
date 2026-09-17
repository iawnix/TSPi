"""Backend contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib


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


class Backend(ABC):
    """Calculation adapter boundary."""

    name: str

    @abstractmethod
    def prepare(self, task: BackendTask) -> PreparedTask:
        """Return ResearchNode-scoped metadata without mutating canonical state."""


def configured_backend_command(name: str, default: str) -> str:
    """Resolve an optional installation-owned local backend executable."""
    configured = os.environ.get("TS_LOCAL_CONFIG", "").strip()
    if not configured:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            configured = str(Path(install_root) / ".pi" / "local.toml")
    if not configured:
        return default
    path = Path(configured).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return default
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return default
    table = raw.get("backends", raw.get("local", raw))
    if not isinstance(table, dict):
        return default
    value = table.get(name, default)
    if isinstance(value, dict):
        value = value.get("command", default)
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        return default
    return value.strip()
