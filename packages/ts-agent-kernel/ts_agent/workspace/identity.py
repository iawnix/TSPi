"""Persistent, non-scientific identity for one TS workspace."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from ts_agent.io import now_iso
from .schema_validation import SchemaValidationError, validate_contract
from .path_safety import has_symlink_component, lexical_path, path_has_symlink


IDENTITY_REF = ".agents/workspace-identity.json"
IDENTITY_SCHEMA = "ts-workspace-identity/1"
WORKSPACE_ID_PATTERN = re.compile(r"^ws_[0-9a-f]{24}$")


class WorkspaceIdentityError(ValueError):
    """Raised when a persisted workspace identity is missing or invalid."""


def workspace_identity_path(root: str | Path) -> Path:
    return lexical_path(root) / IDENTITY_REF


def read_workspace_identity(root: str | Path) -> dict[str, str]:
    root_path = lexical_path(root)
    path = root_path / IDENTITY_REF
    if path_has_symlink(root_path) or has_symlink_component(root_path, path):
        raise WorkspaceIdentityError(f"workspace identity path cannot contain a symbolic link: {path}")
    if not path.is_file():
        raise WorkspaceIdentityError(f"workspace identity does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        validate_contract("workspace_identity.schema.json", record)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        raise WorkspaceIdentityError(f"invalid workspace identity: {path}: {exc}") from exc
    return {str(key): str(value) for key, value in record.items()}


def ensure_workspace_identity(root: str | Path) -> dict[str, str]:
    """Read or atomically create the immutable identity for one workspace."""

    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise WorkspaceIdentityError(f"workspace root cannot contain a symbolic link: {root_path}")
    path = root_path / IDENTITY_REF
    if path.exists() or path.is_symlink():
        return read_workspace_identity(root)

    if has_symlink_component(root_path, path.parent):
        raise WorkspaceIdentityError(f"workspace identity path cannot contain a symbolic link: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "schema_version": IDENTITY_SCHEMA,
        "workspace_id": f"ws_{uuid.uuid4().hex[:24]}",
        "created_at": now_iso(),
    }
    validate_contract("workspace_identity.schema.json", record)
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(path.parent, directory_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return read_workspace_identity(root)


def workspace_id(root: str | Path, *, create: bool = False) -> str:
    record = ensure_workspace_identity(root) if create else read_workspace_identity(root)
    value = record["workspace_id"]
    if not WORKSPACE_ID_PATTERN.fullmatch(value):
        raise WorkspaceIdentityError(f"invalid workspace_id: {value}")
    return value
