"""Workspace mode binding used by the public ResearchAgent launcher.

The launcher is a Host boundary, so it may create and admit a workspace, but
it does not implement ResearchMap mutations.  The manifest is deliberately
small and matches the transport-neutral Research Agent workspace contract.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "research_agent_workspace_1"
WORKSPACE_MODES = frozenset({"light", "research"})
WORKSPACE_STATES = frozenset({"initializing", "ready", "admission_pending", "failed"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

_COMMON_DIRECTORIES = ("inputs", "artifacts", "runs", "logs")
_MODE_DIRECTORIES = {
    "light": ("scratch", "sessions"),
    "research": (
        "research_map",
        "memory",
        "lifecycle",
        "checkpoints",
        "nodes",
        "evidence",
        "monitor",
        "environments",
    ),
}


class WorkspaceModeError(RuntimeError):
    """Raised when a workspace mode cannot be created or attached safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise WorkspaceModeError(f"{field} must be a non-empty identifier")
    return value


def _mode(value: Any) -> str:
    if value not in WORKSPACE_MODES:
        raise WorkspaceModeError("workspace_mode must be one of: light, research")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise WorkspaceModeError(f"workspace_manifest_symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceModeError(f"workspace_manifest_missing: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceModeError(f"workspace_manifest_invalid: {path}") from exc
    if not isinstance(value, dict):
        raise WorkspaceModeError("workspace_manifest_invalid: object required")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _validate(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise WorkspaceModeError("unsupported_workspace_manifest")
    _identifier(manifest.get("workspace_id"), "workspace_id")
    _mode(manifest.get("workspace_mode"))
    if manifest.get("state") not in WORKSPACE_STATES:
        raise WorkspaceModeError("invalid_workspace_state")
    if Path(str(manifest.get("workspace_root", ""))).expanduser().resolve() != root.resolve():
        raise WorkspaceModeError("workspace_root_mismatch")
    directories = manifest.get("directories")
    if not isinstance(directories, list) or not directories:
        raise WorkspaceModeError("workspace_directories_missing")
    return manifest


def _research_seed(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    created_at = manifest["created_at"]
    workspace_id = manifest["workspace_id"]
    return {
        "context": {
            "schema_version": "research_map_context_1",
            "workspace_id": workspace_id,
            "workspace_mode": "research",
            "revision": 0,
            "lifecycle_state": "admission_pending",
            "phases": [],
            "claims": [],
            "nodes": [],
            "gates": [],
            "focus": {"claim_ids": [], "node_ids": []},
        },
        "liveness": {
            "schema_version": "research_liveness_1",
            "workspace_id": workspace_id,
            "state": "admission_pending",
            "revision": 0,
        },
        "memory": {
            "schema_version": "research_memory_index_1",
            "workspace_id": workspace_id,
            "entries": [],
        },
        "checkpoint": {
            "schema_version": "research_checkpoint_1",
            "checkpoint_id": "checkpoint_0",
            "workspace_id": workspace_id,
            "kind": "workspace_genesis",
            "revision": 0,
            "lifecycle_state": "admission_pending",
            "created_at": created_at,
        },
    }


def initialize_workspace(root: str | Path, workspace_id: str, workspace_mode: str) -> dict[str, Any]:
    """Create or attach a mode-bound workspace manifest."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    identifier = _identifier(workspace_id, "workspace_id")
    selected_mode = _mode(workspace_mode)
    manifest_path = path / "workspace_manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _validate(_read_json(manifest_path), path)
        if manifest["workspace_id"] != identifier:
            raise WorkspaceModeError("workspace_id_mismatch")
        if manifest["workspace_mode"] != selected_mode:
            raise WorkspaceModeError("workspace_mode_mismatch")
        if manifest["state"] not in {"ready", "admission_pending"}:
            raise WorkspaceModeError(f"workspace_initialization_incomplete: {manifest['state']}")
        return manifest

    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    created_at = _now()
    initial_state = "ready" if selected_mode == "light" else "admission_pending"
    directories = [*_COMMON_DIRECTORIES, *_MODE_DIRECTORIES[selected_mode]]
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "workspace_id": identifier,
        "workspace_mode": selected_mode,
        "profile_id": f"{selected_mode}_workspace_1",
        "state": initial_state,
        "workspace_root": str(path),
        "created_at": created_at,
        "directories": directories,
        "research_kernel": (
            {"initialized": True, "admission_required": True, "revision": 0}
            if selected_mode == "research"
            else {"initialized": False, "admission_required": False, "revision": None}
        ),
    }
    _write_json(manifest_path, {**manifest, "state": "initializing"})
    try:
        for directory in directories:
            directory_path = path / directory
            directory_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory_path.chmod(0o700)
        if selected_mode == "research":
            seed = _research_seed(manifest)
            _write_json(path / "research_map/context.json", seed["context"])
            _write_json(path / "lifecycle/liveness.json", seed["liveness"])
            _write_json(path / "memory/index.json", seed["memory"])
            _write_json(path / "checkpoints/checkpoint_0.json", seed["checkpoint"])
        _write_json(manifest_path, manifest)
        return manifest
    except BaseException as exc:
        _write_json(manifest_path, {**manifest, "state": "failed", "failure": str(exc)})
        raise


def admit_research_workspace(root: str | Path) -> dict[str, Any]:
    """Perform the Host-only admission transition for a research workspace."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    manifest_path = path / "workspace_manifest.json"
    manifest = _validate(_read_json(manifest_path), path)
    if manifest["workspace_mode"] != "research":
        raise WorkspaceModeError("workspace_admission_not_required")
    if manifest["state"] == "ready":
        return manifest
    if manifest["state"] != "admission_pending":
        raise WorkspaceModeError(f"workspace_admission_invalid_state: {manifest['state']}")
    admitted_at = _now()
    context_path = path / "research_map/context.json"
    liveness_path = path / "lifecycle/liveness.json"
    context = _read_json(context_path)
    liveness = _read_json(liveness_path)
    if context.get("lifecycle_state") != "admission_pending" or liveness.get("state") != "admission_pending":
        raise WorkspaceModeError("research_lifecycle_state_mismatch")
    _write_json(context_path, {**context, "lifecycle_state": "admitted", "admitted_at": admitted_at})
    _write_json(liveness_path, {**liveness, "state": "admitted", "admitted_at": admitted_at})
    admitted = {
        **manifest,
        "state": "ready",
        "admitted_at": admitted_at,
        "research_kernel": {**manifest["research_kernel"], "admission_required": False},
    }
    _write_json(manifest_path, admitted)
    return admitted


def read_workspace_mode(root: str | Path) -> str:
    """Read the immutable mode from an existing framework workspace."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    manifest = _validate(_read_json(path / "workspace_manifest.json"), path)
    return manifest["workspace_mode"]
