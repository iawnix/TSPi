"""Bootstrap and classify ResearchMap workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .engine import init_workspace
from .identity import IDENTITY_REF, read_workspace_identity
from .path_safety import lexical_path, path_has_symlink
from .validator import validate_workspace


BOOTSTRAP_SCHEMA = "research-map-bootstrap/1"
CANONICAL_FILES = ("workspace.json", "research_map.json", "transactions.jsonl")
CANONICAL_DIRS = ("nodes", "operations", "scratch", "inputs")
UNSUPPORTED_FILES = (
    "research_state.json",
    "phases.json",
    "claims.json",
    "claim_relations.json",
    "research_nodes.json",
    "observations.json",
    "proof_specs.json",
    "validation_results.json",
    "findings.json",
    "gate_specs.json",
    "gate_results.json",
    "decision_log.jsonl",
    "transaction_log.jsonl",
)


class WorkspaceBootstrapState(str, Enum):
    FRESH = "fresh"
    VALID = "valid"
    PARTIAL = "partial"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    INVALID = "invalid"


@dataclass(frozen=True)
class WorkspaceClassification:
    root: Path
    state: WorkspaceBootstrapState
    details: tuple[str, ...] = ()


class WorkspaceBootstrapError(ValueError):
    """Raised when a workspace cannot safely start."""

    def __init__(self, state: WorkspaceBootstrapState, message: str):
        super().__init__(message)
        self.state = state


def classify_workspace(root: str | Path) -> WorkspaceClassification:
    requested = lexical_path(root)
    if path_has_symlink(requested):
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID, ("workspace root is a symbolic link",))
    if requested.exists() and not requested.is_dir():
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID, ("workspace root is not a directory",))
    root_path = requested
    if not root_path.exists():
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)
    unsupported = [f"unsupported legacy file: {name}" for name in UNSUPPORTED_FILES if (root_path / name).exists()]
    if unsupported:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.UNSUPPORTED_LAYOUT, tuple(unsupported))
    markers = _canonical_markers(root_path)
    present = {name for name, path in markers.items() if path.exists()}
    if not present:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)
    missing = sorted(set(markers) - present)
    if missing:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.PARTIAL, (f"missing canonical paths: {', '.join(missing)}",))
    validation = validate_workspace(root_path)
    if validation.get("valid") is not True:
        errors = tuple(
            str(item.get("message"))
            for item in validation.get("findings", [])
            if isinstance(item, dict)
        )
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.INVALID, errors or ("workspace validation failed",))
    return WorkspaceClassification(root_path, WorkspaceBootstrapState.VALID)


def bootstrap_workspace(root: str | Path) -> dict[str, Any]:
    classification = classify_workspace(root)
    root_path = classification.root
    if classification.state is WorkspaceBootstrapState.FRESH:
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        initialized = init_workspace(root_path)
        validation = validate_workspace(root_path)
        if initialized.get("valid") is not True or validation.get("valid") is not True:
            raise WorkspaceBootstrapError(WorkspaceBootstrapState.INVALID, "workspace initialization did not produce a valid ResearchMap")
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "root": str(root_path),
            "state": "initialized",
            "created": True,
            "workspace_id": initialized["workspace_id"],
            "validation": validation,
        }
    if classification.state is WorkspaceBootstrapState.VALID:
        validation = validate_workspace(root_path)
        identity = read_workspace_identity(root_path)
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "root": str(root_path),
            "state": "existing",
            "created": False,
            "workspace_id": identity["workspace_id"],
            "validation": validation,
        }
    detail = "; ".join(classification.details)
    message = {
        WorkspaceBootstrapState.UNSUPPORTED_LAYOUT: "legacy workspace layout is not supported",
        WorkspaceBootstrapState.PARTIAL: "partial workspace cannot be repaired during startup",
        WorkspaceBootstrapState.INVALID: "invalid workspace cannot be started",
    }.get(classification.state, "workspace cannot be started")
    if detail:
        message = f"{message}: {detail}"
    raise WorkspaceBootstrapError(classification.state, message)


def _canonical_markers(root: Path) -> dict[str, Path]:
    return {
        **{name: root / name for name in CANONICAL_FILES},
        **{name: root / name for name in CANONICAL_DIRS},
        IDENTITY_REF: root / IDENTITY_REF,
    }
