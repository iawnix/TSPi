"""Deterministic research kernel for transition-state workspaces."""

from .bootstrap import WorkspaceBootstrapError, WorkspaceBootstrapState, bootstrap_workspace, classify_workspace
from .artifacts import (
    WorkspaceArtifactError,
    list_workspace_artifacts,
    resolve_workspace_artifact_ids,
    resolve_workspace_artifact_ref,
)
from .candidates import (
    ObservationCandidateError,
    build_observation_candidates,
    load_observation_candidate,
    validate_observation_candidates,
    validate_promoted_candidate,
)
from .context import build_review_snapshot, compile_context, gate_capabilities, proof_capabilities
from .engine import change_workspace, init_workspace
from .errors import ContractError, WorkspaceValidationError
from .identity import ensure_workspace_identity, read_workspace_identity, workspace_id
from .operational import calculation_attempt_index
from .validator import validate_workspace

__all__ = [
    "ContractError",
    "ObservationCandidateError",
    "WorkspaceArtifactError",
    "WorkspaceBootstrapError",
    "WorkspaceBootstrapState",
    "WorkspaceValidationError",
    "change_workspace",
    "calculation_attempt_index",
    "bootstrap_workspace",
    "build_observation_candidates",
    "build_review_snapshot",
    "classify_workspace",
    "compile_context",
    "ensure_workspace_identity",
    "init_workspace",
    "list_workspace_artifacts",
    "load_observation_candidate",
    "read_workspace_identity",
    "resolve_workspace_artifact_ids",
    "resolve_workspace_artifact_ref",
    "validate_observation_candidates",
    "validate_promoted_candidate",
    "validate_workspace",
    "proof_capabilities",
    "gate_capabilities",
    "workspace_id",
]
