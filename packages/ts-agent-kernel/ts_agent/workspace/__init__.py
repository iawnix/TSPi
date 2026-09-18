"""Workspace boundary for canonical ResearchMap state."""

from .bootstrap import WorkspaceBootstrapError, WorkspaceBootstrapState, bootstrap_workspace, classify_workspace
from .engine import change_workspace, init_workspace, load_research_map
from .errors import ContractError
from .identity import ensure_workspace_identity, read_workspace_identity, workspace_id
from .validator import validate_workspace

__all__ = [
    "ContractError",
    "WorkspaceBootstrapError",
    "WorkspaceBootstrapState",
    "bootstrap_workspace",
    "change_workspace",
    "classify_workspace",
    "ensure_workspace_identity",
    "init_workspace",
    "load_research_map",
    "read_workspace_identity",
    "validate_workspace",
    "workspace_id",
]
