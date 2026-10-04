"""Read-only diagnostics for canonical Research Agent workspace state.

The canonical runtime owns ``workspace_manifest.json`` and
``research_map/context.json``. Retired JSON/SQLite stores are reported as
errors so this command cannot accidentally bless a mixed or legacy layout.
It is never a migration or runtime fallback path.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


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
    legacy_map = _read_json_source(root_path / "research_map.json", "legacy_json", findings)
    sqlite_snapshot = _read_sqlite_source(root_path / "research.db", findings)
    for name, value in (("manifest", manifest), ("context", context), ("legacy_json", legacy_map), ("sqlite", sqlite_snapshot)):
        if value is not None:
            sources[name] = value

    _validate_manifest_context(manifest, context, findings)
    _compare_sources(sources, findings)

    return _result(root_path, findings, sources)


def doctor_workspace(root: str | Path) -> dict[str, Any]:
    """Public semantic alias for :func:`inspect_workspace`."""

    return inspect_workspace(root)


def _read_json_source(path: Path, name: str, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    relative = str(path.name if name == "legacy_json" else path)
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
        # Older manifests did not persist map_id. Their ResearchMap seed has
        # always used the canonical ``map_<workspace_id>`` namespace; falling
        # back to the bare workspace id made every such workspace appear
        # corrupt to the doctor.
        "map_id": value.get("map_id") or (
            f"map_{value.get('workspace_id')}"
            if name == "manifest" and value.get("workspace_id")
            else value.get("workspace_id")
        ),
        "workspace_id": value.get("workspace_id"),
        "workspace_mode": value.get("workspace_mode"),
        "schema_version": value.get("schema_version"),
    }


def _read_sqlite_source(path: Path, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    relative = str(path.name)
    if path.is_symlink():
        _finding(findings, "error", "symlinked_storage", f"storage source is a symbolic link: {path}", relative)
        return None
    connection: sqlite3.Connection | None = None
    try:
        # mode=ro is important: the doctor must never create a database or
        # mutate journal state while inspecting a workspace.
        # ``immutable=1`` prevents SQLite from attempting to create journal
        # or WAL sidecars when the workspace directory is intentionally
        # private (for example mode 0700).  The doctor is read-only by
        # contract, so stale WAL state is reported by the normal revision and
        # identity comparisons instead of being merged during inspection.
        uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'research_map'"
        ).fetchone()
        if table is None:
            _finding(findings, "error", "invalid_sqlite_storage", "research.db has no research_map table", relative)
            return None
        row = connection.execute(
            "SELECT map_id, revision, payload FROM research_map WHERE singleton = 1"
        ).fetchone()
        if row is None:
            _finding(findings, "error", "empty_sqlite_storage", "research.db has no ResearchMap snapshot", relative)
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as exc:
            _finding(findings, "error", "invalid_sqlite_payload", f"research.db payload is invalid: {exc}", relative)
            payload = {}
        payload_revision = payload.get("revision") if isinstance(payload, dict) else None
        if payload_revision != row["revision"]:
            _finding(
                findings,
                "error",
                "sqlite_revision_payload_mismatch",
                "research.db row revision does not match its serialized payload",
                relative,
            )
        return {
            "kind": "sqlite",
            "path": str(path),
            "revision": row["revision"] if type(row["revision"]) is int and row["revision"] >= 0 else None,
            "map_id": row["map_id"],
            "workspace_id": payload.get("workspace_id") if isinstance(payload, dict) else None,
            "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        }
    except (OSError, sqlite3.DatabaseError) as exc:
        _finding(findings, "error", "invalid_sqlite_storage", f"cannot read research.db: {exc}", relative)
        return None
    finally:
        if connection is not None:
            connection.close()


def _validate_manifest_context(
    manifest: dict[str, Any] | None,
    context: dict[str, Any] | None,
    findings: list[dict[str, Any]],
) -> None:
    if manifest is None:
        return
    if manifest.get("schema_version") != "research_state_workspace_1":
        _finding(findings, "error", "unsupported_workspace_manifest", "workspace manifest schema is unsupported", "workspace_manifest.json")
    mode = manifest.get("workspace_mode")
    kernel = manifest.get("research_state")
    kernel_revision = (
        kernel.get("revision")
        if isinstance(kernel, dict)
        else manifest.get("kernel_revision")
    )
    if mode == "research":
        if type(kernel_revision) is not int or kernel_revision < 0:
            _finding(findings, "error", "invalid_kernel_revision", "research manifest must contain a non-negative kernel revision", "workspace_manifest.json")
        if context is None:
            _finding(findings, "error", "research_context_missing", "research workspace is missing research_map/context.json", "research_map/context.json")
    elif mode != "research":
        _finding(findings, "error", "research_workspace_required", "workspace must use the Research workspace contract", "workspace_manifest.json")
    if context is not None:
        if context.get("schema_version") != "research_map_context_1":
            _finding(findings, "error", "unsupported_research_context", "ResearchMap context schema is unsupported", "research_map/context.json")
        if manifest.get("workspace_id") != context.get("workspace_id"):
            _finding(findings, "error", "workspace_identity_mismatch", "manifest and ResearchMap context workspace IDs differ", "research_map/context.json")
        if type(kernel_revision) is int and context.get("revision") != kernel_revision:
            _finding(findings, "error", "manifest_context_revision_mismatch", "manifest kernel revision differs from ResearchMap context revision", "research_map/context.json")


def _compare_sources(sources: dict[str, dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    revision_sources = {
        name: source["revision"]
        for name, source in sources.items()
        if name != "manifest" and type(source.get("revision")) is int
    }
    if len(set(revision_sources.values())) > 1:
        _finding(
            findings,
            "error",
            "research_revision_mismatch",
            "ResearchMap storage revisions disagree: " + ", ".join(f"{name}={revision}" for name, revision in sorted(revision_sources.items())),
            ",".join(sorted(source["path"] for source in sources.values())),
        )
    legacy = [name for name in ("legacy_json", "sqlite") if name in sources]
    if legacy:
        _finding(
            findings,
            "error",
            "legacy_research_storage",
            "retired ResearchMap storage is not supported; remove the legacy files before opening the workspace",
            ",".join(sources[name]["path"] for name in legacy),
        )
    identity_sources = {
        name: source.get("map_id")
        for name, source in sources.items()
        if source.get("map_id") is not None
    }
    if len(set(identity_sources.values())) > 1:
        _finding(
            findings,
            "error",
            "research_identity_mismatch",
            "ResearchMap storage identities disagree: " + ", ".join(f"{name}={value}" for name, value in sorted(identity_sources.items())),
            ",".join(sorted(source["path"] for source in sources.values())),
        )


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
