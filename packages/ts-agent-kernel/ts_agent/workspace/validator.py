"""Validation for the canonical ResearchMap workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_agent.io import read_json
from ts_agent.runtime.workspace_mode import WorkspaceModeError, validate_workspace_manifest

from ts_agent.path_safety import has_symlink_component, lexical_path, path_has_symlink


VALIDATION_SCHEMA = "research-map-validation/1"


def validate_workspace(root: str | Path, *, read_only: bool = False) -> dict[str, Any]:
    """Validate the canonical Research Agent workspace contract.

    ``read_only`` is retained as a harmless call-site option; validation
    never creates locks or storage. The retired ``workspace.json`` /
    ``research_map.json`` / SQLite layout is reported as invalid.
    """

    del read_only
    root_path = lexical_path(root)
    findings: list[dict[str, str]] = []
    if path_has_symlink(root_path):
        _finding(findings, "workspace_path_symlink", "workspace root contains a symbolic link", ".")
        return _result(findings)
    if not root_path.is_dir():
        _finding(findings, "missing_workspace", "workspace root does not exist", ".")
        return _result(findings)
    manifest_path = root_path / "workspace_manifest.json"
    if has_symlink_component(root_path, manifest_path) or manifest_path.is_symlink():
        _finding(findings, "workspace_manifest_symlink", "workspace manifest is a symbolic link", "workspace_manifest.json")
        return _result(findings)
    if not manifest_path.is_file():
        _finding(findings, "workspace_manifest_missing", "workspace manifest is missing", "workspace_manifest.json")
        return _result(findings)
    try:
        manifest = read_json(manifest_path)
        validate_workspace_manifest(manifest, root_path)
    except (OSError, ValueError, WorkspaceModeError) as exc:
        _finding(findings, "invalid_workspace_manifest", str(exc), "workspace_manifest.json")
    return _result(findings)


def _finding(target: list[dict[str, str]], code: str, message: str, path: str) -> None:
    target.append({"severity": "error", "code": code, "message": message, "path": path})


def _result(findings: list[dict[str, str]]) -> dict[str, Any]:
    return {"schema_version": VALIDATION_SCHEMA, "valid": not findings, "findings": findings}
