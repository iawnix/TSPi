"""Validate and write metadata that binds a TSPi installation to its root."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


INSTALLATION_MARKER_SCHEMA = "tspi-installation-root/1"
PACKAGE_STATE_SCHEMA = "tspi-package-install/1"
WORKSPACE_ROOT_SCHEMA = "tspi-workspace-root/1"
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def read_installation_metadata(
    root: Path,
    *,
    require_ownership: bool = False,
    strict_package_state: bool = True,
) -> dict[str, object]:
    marker_path = root / ".pi/tspi/installation.json"
    state_path = root / ".pi/packages/tspi/install-state.json"
    marker_valid = False
    if marker_path.exists() or marker_path.is_symlink():
        marker = _read_object(marker_path, "installation ownership marker")
        marker_valid = marker == {"schema_version": INSTALLATION_MARKER_SCHEMA, "install_root": str(root)}
        if not marker_valid:
            raise ValueError(f"installation ownership marker does not match this directory: {marker_path}")

    release_id: str | None = None
    state_valid = False
    state_error: str | None = None
    state_present = state_path.exists() or state_path.is_symlink()
    if state_present:
        try:
            state = _read_object(state_path, "installed package state")
            release_id = state.get("current_release_id")
            recorded_package = state.get("package_root")
            expected = root / ".pi/packages/tspi/releases" / release_id if isinstance(release_id, str) else None
            state_valid = (
                state.get("schema_version") == PACKAGE_STATE_SCHEMA
                and isinstance(release_id, str)
                and RELEASE_ID.fullmatch(release_id) is not None
                and isinstance(recorded_package, str)
                and expected is not None
                and Path(recorded_package).expanduser() == expected
            )
            if not state_valid:
                raise ValueError(f"installed package state does not belong to this directory: {state_path}")
        except ValueError as error:
            if strict_package_state or not marker_valid:
                raise
            release_id = None
            state_error = str(error)

    if require_ownership and not marker_valid and not state_valid:
        raise ValueError(
            f"does not contain trusted TSPi installation metadata: {root}; "
            "refusing to treat a source checkout or arbitrary directory as an installation"
        )
    return {
        "owned": marker_valid or state_valid,
        "ownership": "marker" if marker_valid else ("package state" if state_valid else None),
        "release_id": release_id,
        "state_present": state_present,
        "state_error": state_error,
    }


def write_installation_marker(root: Path) -> Path:
    private = root / ".pi/tspi"
    if private.is_symlink() or not private.is_dir():
        raise ValueError(f"installer control path must be a physical directory: {private}")
    marker = private / "installation.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".installation.", dir=private)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"schema_version": INSTALLATION_MARKER_SCHEMA, "install_root": str(root)},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, marker)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return marker


def read_workspace_root(root: Path) -> Path:
    """Return the installation-owned workspace container configuration."""

    path = root / ".pi/tspi/workspace-root.json"
    if not path.exists() and not path.is_symlink():
        return root / "workspaces"
    value = _read_object(path, "workspace root configuration")
    if set(value) != {"schema_version", "workspace_root"} or value.get("schema_version") != WORKSPACE_ROOT_SCHEMA:
        raise ValueError(f"workspace root configuration is invalid: {path}")
    configured = value.get("workspace_root")
    if not isinstance(configured, str) or not configured or any(ord(character) < 32 for character in configured):
        raise ValueError(f"workspace root configuration is invalid: {path}")
    workspace_root = Path(configured).expanduser()
    if not workspace_root.is_absolute():
        raise ValueError(f"workspace root configuration must be absolute: {path}")
    return workspace_root


def write_workspace_root(root: Path, workspace_root: Path) -> Path:
    """Atomically persist the workspace container without changing ownership metadata."""

    private = root / ".pi/tspi"
    if private.is_symlink() or not private.is_dir():
        raise ValueError(f"installer control path must be a physical directory: {private}")
    path = private / "workspace-root.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".workspace-root.", dir=private)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"schema_version": WORKSPACE_ROOT_SCHEMA, "workspace_root": str(workspace_root)},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return path


def _read_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is invalid: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value
