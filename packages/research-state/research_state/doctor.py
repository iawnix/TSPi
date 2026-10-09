"""Read-only diagnostics for canonical Research Agent workspace state.

The canonical runtime owns ``workspace_manifest.json`` and
``research_map/context.json``. Retired JSON/SQLite stores are reported as
errors so this command cannot accidentally bless a mixed or legacy layout.
It is never a migration or runtime fallback path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from tspi_foundation.protocol import RETIRED_WORKSPACE_FILES


DOCTOR_SCHEMA = "research-agent-workspace-doctor/1"


def inspect_workspace(root: str | Path) -> dict[str, Any]:
    """Inspect workspace storage without creating locks, databases, or files.

    ``valid`` is false whenever an authoritative-looking source has malformed
    data, its revision/identity conflicts with another source, or any retired
    JSON/SQLite source is present. Legacy stores are diagnostics only and are
    never accepted as an alternate authority.
    """

    requested = Path(root).expanduser()
    root_path = requested.absolute()
    findings: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}

    if requested.is_symlink():
        _finding(findings, "error", "workspace_root_symlink", "workspace root is a symbolic link", ".")
        return _result(root_path, findings, sources)
    if not requested.exists():
        _finding(findings, "error", "workspace_missing", "workspace root does not exist", ".")
        return _result(root_path, findings, sources)
    if not requested.is_dir():
        _finding(findings, "error", "workspace_not_directory", "workspace root is not a directory", ".")
        return _result(root_path, findings, sources)

    manifest = _read_json_source(root_path / "workspace_manifest.json", "manifest", findings)
    context = _read_json_source(root_path / "research_map" / "context.json", "context", findings)
    for name in RETIRED_WORKSPACE_FILES:
        path = root_path / name
        if path.exists() or path.is_symlink():
            _finding(findings, "error", "unsupported_workspace_storage", "retired storage is unsupported; create a new workspace", name)
    for name, value in (("manifest", manifest), ("context", context)):
        if value is not None:
            sources[name] = value

    _validate_manifest_context(manifest, context, findings)

    return _result(root_path, findings, sources)


def _read_json_source(path: Path, name: str, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    relative = str(path)
    if path.is_symlink():
        _finding(findings, "error", "symlinked_storage", f"storage source is a symbolic link: {path}", relative)
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _finding(findings, "error", "invalid_storage_json", f"cannot read {name}: {exc}", relative)
        return None
    if not isinstance(value, dict):
        _finding(findings, "error", "invalid_storage_document", f"{name} must contain an object", relative)
        return None
    revision = value.get("revision")
    if revision is not None and (type(revision) is not int or revision < 0):
        _finding(findings, "error", "invalid_storage_revision", f"{name} revision must be a non-negative integer", relative)
    return {
        "kind": name,
        "path": str(path),
        "revision": revision if type(revision) is int and revision >= 0 else None,
        "kernel_revision": (
            value.get("research_state", {}).get("revision")
            if isinstance(value.get("research_state"), dict)
            else None
        ),
        "map_id": value.get("map_id"),
        "workspace_id": value.get("workspace_id"),
        "workspace_mode": value.get("workspace_mode"),
        "schema_version": value.get("schema_version"),
    }


def _validate_manifest_context(
    manifest: dict[str, Any] | None,
    context: dict[str, Any] | None,
    findings: list[dict[str, Any]],
) -> None:
    if manifest is None:
        return
    if manifest.get("schema_version") != "research_state_workspace_2":
        _finding(findings, "error", "unsupported_workspace_manifest", "workspace manifest schema is unsupported", "workspace_manifest.json")
    mode = manifest.get("workspace_mode")
    kernel_revision = manifest.get("kernel_revision")
    if mode == "research":
        if type(kernel_revision) is not int or kernel_revision < 0:
            _finding(findings, "error", "invalid_kernel_revision", "research manifest must contain a non-negative kernel revision", "workspace_manifest.json")
        if context is None:
            _finding(findings, "error", "research_context_missing", "research workspace is missing research_map/context.json", "research_map/context.json")
    elif mode != "research":
        _finding(findings, "error", "research_workspace_required", "workspace must use the Research workspace contract", "workspace_manifest.json")
    if context is not None:
        if manifest.get("map_id") != context.get("map_id"):
            _finding(findings, "error", "research_identity_mismatch", "manifest and context map IDs differ", "research_map/context.json")
        if context.get("schema_version") != "research_map_context_2":
            _finding(findings, "error", "unsupported_research_context", "ResearchMap context schema is unsupported", "research_map/context.json")
        if manifest.get("workspace_id") != context.get("workspace_id"):
            _finding(findings, "error", "workspace_identity_mismatch", "manifest and ResearchMap context workspace IDs differ", "research_map/context.json")
        if type(kernel_revision) is int and context.get("revision") != kernel_revision:
            _finding(findings, "error", "manifest_context_revision_mismatch", "manifest kernel revision differs from ResearchMap context revision", "research_map/context.json")


def _finding(target: list[dict[str, Any]], severity: str, code: str, message: str, path: str) -> None:
    target.append({"severity": severity, "code": code, "message": message, "path": path})


def _result(root: Path, findings: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors = [finding for finding in findings if finding["severity"] == "error"]
    if errors:
        status = "blocked"
    elif sources:
        status = "healthy"
    else:
        status = "empty"
    return {
        "schema_version": DOCTOR_SCHEMA,
        "root": str(root),
        "valid": not errors,
        "status": status,
        "findings": findings,
        "sources": sources,
    }
