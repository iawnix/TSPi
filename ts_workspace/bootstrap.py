"""Idempotent startup bootstrap for clean v5 workspaces only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .engine import init_workspace
from .identity import IDENTITY_REF, read_workspace_identity
from .state import LEGACY_MARKERS, OPTIONAL_DIRS, REQUIRED_DIRS, REQUIRED_FILES, WORKSPACE_FILE
from .validator import validate_workspace


BOOTSTRAP_SCHEMA = "ts-workspace-bootstrap/3"


class WorkspaceBootstrapState(str, Enum):
    FRESH = "fresh"
    VALID_V5 = "valid_v5"
    PARTIAL_V5 = "partial_v5"
    LEGACY_UNSUPPORTED = "legacy_unsupported"
    INVALID_V5 = "invalid_v5"


@dataclass(frozen=True)
class WorkspaceClassification:
    root: Path
    state: WorkspaceBootstrapState
    details: tuple[str, ...] = ()


class WorkspaceBootstrapError(ValueError):
    """Raised when startup cannot safely initialize or reuse a v5 workspace."""

    def __init__(self, state: WorkspaceBootstrapState, message: str):
        super().__init__(message)
        self.state = state


def classify_workspace(root: str | Path) -> WorkspaceClassification:
    requested = Path(root).expanduser()
    if requested.is_symlink():
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID_V5, ("workspace root is a symbolic link",))
    if requested.exists() and not requested.is_dir():
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID_V5, ("workspace root is not a directory",))
    root_path = requested.resolve()
    if not root_path.exists():
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)

    unsafe = _unsafe_workspace_paths(root_path)
    if unsafe:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.INVALID_V5, tuple(unsafe))
    legacy = _legacy_details(root_path)
    if legacy:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.LEGACY_UNSUPPORTED, tuple(legacy))

    markers = _canonical_markers(root_path)
    present = sorted(ref for ref, path in markers.items() if path.exists())
    if not present:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)
    missing = sorted(set(markers) - set(present))
    if missing:
        return WorkspaceClassification(
            root_path,
            WorkspaceBootstrapState.PARTIAL_V5,
            (f"missing canonical v5 paths: {', '.join(missing)}",),
        )
    validation = validate_workspace(root_path)
    if validation.get("valid") is not True:
        errors = tuple(
            str(item.get("message"))
            for item in validation.get("findings", [])
            if isinstance(item, dict) and item.get("severity") == "error"
        )
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.INVALID_V5, errors or ("workspace validation failed",))
    return WorkspaceClassification(root_path, WorkspaceBootstrapState.VALID_V5)


def bootstrap_workspace(root: str | Path) -> dict[str, Any]:
    classification = classify_workspace(root)
    root_path = classification.root
    if classification.state is WorkspaceBootstrapState.FRESH:
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        initialized = init_workspace(root_path)
        validation = validate_workspace(root_path)
        if initialized.get("valid") is not True or validation.get("valid") is not True:
            raise WorkspaceBootstrapError(WorkspaceBootstrapState.INVALID_V5, "workspace initialization did not produce a valid v5 workspace")
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "root": str(root_path),
            "state": "initialized",
            "created": True,
            "workspace_id": initialized["workspace_id"],
            "validation": validation,
        }
    if classification.state is WorkspaceBootstrapState.VALID_V5:
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
    if classification.state is WorkspaceBootstrapState.LEGACY_UNSUPPORTED:
        message = "legacy TS workspace is not supported by the v5 runtime; continue it with the matching previous release or start a new v5 workspace"
    elif classification.state is WorkspaceBootstrapState.PARTIAL_V5:
        message = "partially initialized v5 workspace cannot be repaired during startup"
    else:
        message = "invalid v5 workspace cannot be started"
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


def _legacy_details(root: Path) -> list[str]:
    details = [f"legacy marker exists: {name}" for name in sorted(LEGACY_MARKERS) if (root / name).exists()]
    expected_schemas = {
        WORKSPACE_FILE: "ts-workspace/5",
        "research_state.json": "ts-research-state/5",
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
            details.append(f"legacy schema exists: {name}={schema}")
    if (root / "hypotheses.json").exists():
        details.append("legacy marker exists: hypotheses.json")
    return details
