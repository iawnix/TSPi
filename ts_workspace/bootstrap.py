"""Deterministic startup classification for one v3 research workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .engine_v3 import init_workspace
from .identity import IDENTITY_REF, read_workspace_identity
from .state_v3 import OPTIONAL_DIRS, REQUIRED_DIRS, REQUIRED_FILES, RESEARCH_STATE_FILE
from .validator_v3 import validate_workspace


BOOTSTRAP_SCHEMA = "ts-workspace-bootstrap/1"


class WorkspaceBootstrapState(str, Enum):
    FRESH = "fresh"
    VALID_V3 = "valid_v3"
    PARTIAL_V3 = "partial_v3"
    LEGACY_V2 = "legacy_v2"
    INVALID_V3 = "invalid_v3"


@dataclass(frozen=True)
class WorkspaceClassification:
    root: Path
    state: WorkspaceBootstrapState
    details: tuple[str, ...] = ()


class WorkspaceBootstrapError(ValueError):
    """Raised when launcher bootstrap cannot safely initialize or reuse a workspace."""

    def __init__(self, state: WorkspaceBootstrapState, message: str):
        super().__init__(message)
        self.state = state


def classify_workspace(root: str | Path) -> WorkspaceClassification:
    requested = Path(root).expanduser()
    if requested.is_symlink():
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID_V3, ("workspace root is a symbolic link",))
    if requested.exists() and not requested.is_dir():
        return WorkspaceClassification(requested.absolute(), WorkspaceBootstrapState.INVALID_V3, ("workspace root is not a directory",))

    root_path = requested.resolve()
    if not root_path.exists():
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)

    unsafe = _unsafe_workspace_paths(root_path)
    if unsafe:
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.INVALID_V3, tuple(unsafe))

    markers = _canonical_markers(root_path)
    present = sorted(ref for ref, path in markers.items() if path.exists())
    if not present:
        if _looks_like_v2(root_path):
            return WorkspaceClassification(root_path, WorkspaceBootstrapState.LEGACY_V2, ("legacy v2 workspace markers are present",))
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.FRESH)

    if _looks_like_v2(root_path):
        return WorkspaceClassification(root_path, WorkspaceBootstrapState.LEGACY_V2, ("legacy v2 workspace markers are present",))

    missing = sorted(set(markers) - set(present))
    if missing:
        return WorkspaceClassification(
            root_path,
            WorkspaceBootstrapState.PARTIAL_V3,
            (f"missing canonical paths: {', '.join(missing)}",),
        )

    validation = validate_workspace(root_path)
    if validation.get("valid") is not True:
        errors = tuple(
            str(item.get("message"))
            for item in validation.get("findings", [])
            if isinstance(item, dict) and item.get("severity") == "error"
        )
        return WorkspaceClassification(
            root_path,
            WorkspaceBootstrapState.INVALID_V3,
            errors or ("workspace validation failed",),
        )
    return WorkspaceClassification(root_path, WorkspaceBootstrapState.VALID_V3)


def bootstrap_workspace(root: str | Path) -> dict[str, Any]:
    classification = classify_workspace(root)
    root_path = classification.root
    if classification.state is WorkspaceBootstrapState.FRESH:
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        initialized = init_workspace(root_path)
        validation = validate_workspace(root_path)
        if initialized.get("valid") is not True or validation.get("valid") is not True:
            raise WorkspaceBootstrapError(
                WorkspaceBootstrapState.INVALID_V3,
                "workspace initialization did not produce a valid v3 workspace",
            )
        identity = read_workspace_identity(root_path)
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "root": str(root_path),
            "state": "initialized",
            "created": True,
            "workspace_id": identity["workspace_id"],
            "validation": validation,
        }

    if classification.state is WorkspaceBootstrapState.VALID_V3:
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
    if classification.state is WorkspaceBootstrapState.LEGACY_V2:
        message = "legacy v2 workspace requires explicit copy migration"
    elif classification.state is WorkspaceBootstrapState.PARTIAL_V3:
        message = "partially initialized v3 workspace cannot be repaired during startup"
    else:
        message = "invalid v3 workspace cannot be started"
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


def _looks_like_v2(root: Path) -> bool:
    if (root / "hypotheses.json").exists():
        return True
    research_path = root / RESEARCH_STATE_FILE
    if not research_path.is_file() or research_path.is_symlink():
        return False
    try:
        value = json.loads(research_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get("schema_version") == "ts-research-state"
