"""Workspace configuration models for the TS explorer service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExplorerWorkspaceConfig:
    """Configuration for one read-only TS-search workspace exposed by the explorer."""

    workspace_id: str
    display_name: str
    source_directory: Path
    explorer_state_directory: Path
    project_directory: Path | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExplorerServerConfig:
    """Runtime configuration for the read-only TS hypothesis explorer service."""

    workspaces: tuple[ExplorerWorkspaceConfig, ...]
    default_workspace_id: str
    bind_host: str
    bind_port: int
    allow_source_workspace_writes: bool = False
    workspace_registry_path: Path | None = None
    workspace_discovery_roots: tuple[Path, ...] = ()
