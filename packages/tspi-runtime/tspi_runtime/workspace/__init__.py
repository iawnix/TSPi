"""Workspace boundary for canonical ResearchMap state."""

from .bootstrap import WorkspaceBootstrapError, WorkspaceBootstrapState, bootstrap_workspace, classify_workspace
from .errors import ContractError
from .identity import ensure_workspace_identity, read_workspace_identity, workspace_id
from .validator import validate_workspace
from .doctor import doctor_workspace, inspect_workspace

__all__ = [
    "ContractError",
    "WorkspaceBootstrapError",
    "WorkspaceBootstrapState",
    "bootstrap_workspace",
    "classify_workspace",
    "ensure_workspace_identity",
    "read_workspace_identity",
    "validate_workspace",
    "inspect_workspace",
    "doctor_workspace",
    "workspace_id",
]
