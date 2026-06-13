"""Compatibility re-export for explorer workspace registry helpers."""

from transition_state_workflow.base.explorer_registry import (
    DEFAULT_REGISTRY_PATH,
    REGISTRY_SCHEMA,
    default_registry_path,
    default_workspace_id_for_source,
    read_registry_payload,
    register_workspace,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "REGISTRY_SCHEMA",
    "default_registry_path",
    "default_workspace_id_for_source",
    "read_registry_payload",
    "register_workspace",
]
