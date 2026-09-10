"""Idempotent startup bootstrap for supported workspaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .engine import init_workspace
from .identity import IDENTITY_REF, read_workspace_identity
from .state import OPTIONAL_DIRS, REQUIRED_DIRS, REQUIRED_FILES, UNSUPPORTED_MARKERS, WORKSPACE_FILE
from .validator import validate_workspace
from .path_safety import lexical_path, path_has_symlink


BOOTSTRAP_SCHEMA = "ts-workspace-bootstrap/4"


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
    """Raised when startup cannot safely initialize or reuse a workspace."""

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

    unsafe = _unsafe_workspace_paths(root_path)
    if unsafe:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.INVALID, tuple(unsafe))
    unsupported = _unsupported_layout_details(root_path)
    if unsupported:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.UNSUPPORTED_LAYOUT, tuple(unsupported))

    markers = _canonical_markers(root_path)
    present = sorted(ref for ref, path in markers.items() if path.exists())
    if not present:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)
    missing = sorted(set(markers) - set(present))
    if missing:
        return WorkspaceClassification(
            root_path,
            WorkspaceBootstrapState.PARTIAL,
            (f"missing canonical paths: {', '.join(missing)}",),
        )
    validation = validate_workspace(root_path)
    if validation.get("valid") is not True:
        errors = tuple(
            str(item.get("message"))
            for item in validation.get("findings", [])
            if isinstance(item, dict) and item.get("severity") == "error"
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
            raise WorkspaceBootstrapError(WorkspaceBootstrapState.INVALID, "workspace initialization did not produce a valid workspace")
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
    if classification.state is WorkspaceBootstrapState.UNSUPPORTED_LAYOUT:
        message = "unsupported workspace layout cannot be started"
    elif classification.state is WorkspaceBootstrapState.PARTIAL:
        message = "partial workspace cannot be repaired during startup"
    else:
        message = "invalid workspace cannot be started"
    if detail:
        message = f"{message}: {detail}"
    raise WorkspaceBootstrapError(classification.state, message)


def _canonical_markers(root: Path) -> dict[str, Path]:
    return {
        **{name: root / name for name in REQUIRED_FILES},
        **{name: root / name for name in REQUIRED_DIRS},
        IDENTITY_REF: root / IDENTITY_REF,
    }


def _unsafe_workspace_paths(root: Path) -> list[str]:
    unsafe: list[str] = []
    for ref, path in _canonical_markers(root).items():
        if path.is_symlink():
            unsafe.append(f"canonical path cannot be a symbolic link: {ref}")
    for name in sorted(OPTIONAL_DIRS):
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            unsafe.append(f"optional workspace path must be a physical directory: {name}")
    identity_parent = root / Path(IDENTITY_REF).parent
    if identity_parent.is_symlink():
        unsafe.append(f"workspace identity parent cannot be a symbolic link: {identity_parent.relative_to(root)}")
    return unsafe


def _unsupported_layout_details(root: Path) -> list[str]:
    details = [f"unsupported marker exists: {name}" for name in sorted(UNSUPPORTED_MARKERS) if (root / name).exists()]
    expected_schemas = {
        WORKSPACE_FILE: "ts-workspace/6",
        "research_state.json": "ts-research-state/6",
    }
    for name in (WORKSPACE_FILE, "research_state.json"):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        schema = value.get("schema_version") if isinstance(value, dict) else None
        if isinstance(schema, str) and schema != expected_schemas[name]:
            details.append(f"unsupported schema exists: {name}={schema}")
    if (root / "hypotheses.json").exists():
        details.append("unsupported marker exists: hypotheses.json")
    return details
