"""Read-only transport helpers for clients such as TS Web.

The transport deliberately exposes the canonical ``ResearchMap`` document.
It may add workspace/catalog envelopes, but it never builds a second derived
research model or renames domain objects for a client.
"""

from __future__ import annotations

import copy
import json
import posixpath
import re
import stat
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

from tspi_runtime.path_safety import has_symlink_component, lexical_path, path_has_symlink
from .workspace import WorkspaceModeError, validate_workspace_manifest

from .registry import (
    ensure_state_dir,
    find_workspace,
    list_workspaces,
    reconcile_workspace_registry,
    register_workspaces,
    remove_workspace,
    workspace_discovery_roots,
)


PROVIDER_PROTOCOL = "research-map-provider/1"
ERROR_SCHEMA = "research-map-error/1"
WORKSPACE_LIST_SCHEMA = "research-workspace-list/1"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
RESEARCH_CONTEXT_COLLECTIONS = (
    "phases", "claims", "nodes", "findings", "gates", "claim_relations",
    "attempts", "artifacts", "evidence_links", "lifecycle_actions",
    "strategy_plans", "strategy_reviews", "attempt_interpretations",
)


class ResearchWebError(ValueError):
    """A client request cannot be served."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def handle_request(
    state_dir: str | Path,
    request: object,
    *,
    workspace_roots: Sequence[str | Path] | None = None,
) -> Any:
    value = _request_object(request)
    state = ensure_state_dir(state_dir)
    roots = workspace_discovery_roots(state, workspace_roots)
    reconcile_workspace_registry(state, roots)
    operation = value["operation"]
    if operation == "catalog":
        return _catalog(state)
    if operation == "remove":
        return remove_workspace(state, _safe_id(value.get("workspace_id"), "workspace"))
    if operation != "route":
        raise ResearchWebError(f"unsupported provider operation: {operation!r}")
    workspace_id = _safe_id(value.get("workspace_id"), "workspace")
    route = value.get("route")
    if not isinstance(route, str) or route.startswith("/") or ".." in route.split("/"):
        raise ResearchWebError("invalid workspace route")
    query = _query_object(value.get("query"))
    row = find_workspace(state, workspace_id)
    if row is None:
        raise ResearchWebError(f"unknown workspace id: {workspace_id}")
    source_root = row.get("source_root")
    if not isinstance(source_root, str) or not source_root:
        raise ResearchWebError(f"workspace {workspace_id} has no registered location")
    # Registry lookup is canonical-only. The resolved row carries the immutable
    # manifest identity through every response envelope.
    return _route({**row, "source_root": source_root}, route.strip("/"), query)


def register_sources(
    state_dir: str | Path,
    source_roots: Sequence[str | Path],
    labels: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    return register_workspaces(list(source_roots), state_dir, list(labels or []))


def provider_success_payload(request_id: str, payload: Any) -> dict[str, Any]:
    return {"schema_version": PROVIDER_PROTOCOL, "request_id": request_id, "ok": True, "payload": payload}


def provider_error_payload(request_id: str, error: Exception, *, retryable: bool | None = None) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_PROTOCOL,
        "request_id": request_id,
        "ok": False,
        "error": {
            "schema_version": ERROR_SCHEMA,
            "error": str(error)[:4000] or "ResearchMap provider error",
            "retryable": bool(getattr(error, "retryable", False) if retryable is None else retryable),
        },
    }


def _request_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchWebError("provider request must be an object")
    expected = {"schema_version", "request_id", "operation", "workspace_id", "route", "query"}
    required = {"schema_version", "request_id", "operation", "query"}
    if set(value) - expected or required - set(value) or value.get("schema_version") != PROVIDER_PROTOCOL:
        raise ResearchWebError("unsupported provider request schema")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise ResearchWebError("provider request_id must be a bounded string")
    if value.get("operation") not in {"catalog", "route", "remove"}:
        raise ResearchWebError("unsupported provider operation")
    workspace_id = value.get("workspace_id")
    if workspace_id is not None and (
        not isinstance(workspace_id, str) or WORKSPACE_ID_PATTERN.fullmatch(workspace_id) is None
    ):
        raise ResearchWebError("invalid provider workspace_id")
    route = value.get("route")
    if route is not None and (not isinstance(route, str) or len(route) > 256):
        raise ResearchWebError("invalid provider route")
    _query_object(value.get("query"))
    return value


def _query_object(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ResearchWebError("provider query must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str) or len(key) > 80 or len(item) > 4096:
            raise ResearchWebError("provider query values must be bounded strings")
        result[key] = item
    return result


def _catalog(state_dir: Path) -> dict[str, Any]:
    summaries = [_summary(row) for row in list_workspaces(state_dir)]
    available = [row for row in summaries if row["available"]]
    return {
        "schema_version": WORKSPACE_LIST_SCHEMA,
        "default_workspace": available[0]["workspace_id"] if available else (summaries[0]["workspace_id"] if summaries else None),
        "workspaces": summaries,
    }


def _summary(row: dict[str, Any], research_map: Any | None = None) -> dict[str, Any]:
    source_root = str(row.get("source_root") or "")
    workspace_id = str(row.get("workspace_id") or "")
    label = str(row.get("label") or (Path(source_root).name if source_root else workspace_id))
    base = {
        "workspace_id": workspace_id,
        "label": label,
        "available": False,
        "valid": False,
        "revision": None,
        "progress": {},
    }
    if research_map is None:
        try:
            research_map = _load_map(source_root)
        except (OSError, ValueError, ResearchWebError) as error:
            base["load_error"] = _sanitize(str(error), source_root)
            return base
    base.update({"available": True, "valid": True, "revision": research_map.revision, "progress": research_map.progress()})
    return base


def _route(row: dict[str, Any], route: str, query: dict[str, str]) -> Any:
    research_map = _load_map(row["source_root"])
    payload = research_map.to_dict()
    if route in {"", "map"}:
        return {
            "schema_version": "research-map-response/1",
            "workspace": _summary(row, research_map),
            "map": payload,
        }
    if route in {"phases", "claims", "claim_relations", "nodes", "findings", "gates", "lifecycle_actions"}:
        return {"schema_version": "research-map-collection/1", "map_id": research_map.map_id, route: payload[route]}
    if route.startswith("claim/"):
        return _detail(payload, "claims", route[6:])
    if route.startswith("phase/"):
        return _detail(payload, "phases", route[6:])
    if route.startswith("node/"):
        return _detail(payload, "nodes", route[5:])
    if route.startswith("finding/"):
        return _detail(payload, "findings", route[8:])
    if route.startswith("gate/"):
        return _detail(payload, "gates", route[5:])
    if route == "file":
        return _read_node_file(row["source_root"], query.get("path", ""), research_map)
    raise ResearchWebError(f"unknown workspace route: {route}")


def _load_map(source_root: str) -> Any:
    if not _has_new_research_state(source_root):
        raise ResearchWebError("workspace is not an initialized Research Agent workspace")
    try:
        return _FilesystemResearchMap(source_root)
    except (OSError, ValueError, ResearchWebError) as error:
        raise ResearchWebError(str(error), retryable=True) from error


def _has_new_research_state(source_root: str | Path) -> bool:
    root = lexical_path(source_root)
    if path_has_symlink(root) or not (root / "workspace_manifest.json").is_file():
        return False
    try:
        manifest = _read_object(root / "workspace_manifest.json", "workspace_manifest")
        # The provider is a read-only consumer of an admitted workspace.  A
        # manifest in ``admission_pending`` is an internal Host transition and
        # must not become externally routable through the Web protocol.
        validate_workspace_manifest(manifest, root, require_ready=True)
    except (OSError, ValueError, ResearchWebError, WorkspaceModeError):
        return False
    return manifest.get("workspace_mode") == "research"


class _FilesystemResearchMap:
    """Read-only ResearchMap projection for the new filesystem Kernel.

    The Web contract still speaks ``research-map/1`` while the new Kernel
    stores its context as ``research_map_context_1``.  This adapter translates
    only the read shape; all mutations remain owned by the filesystem Kernel.
    """

    def __init__(self, source_root: str | Path) -> None:
        self.root = lexical_path(source_root)
        if path_has_symlink(self.root):
            raise ResearchWebError("workspace path contains a symbolic link")
        manifest = _read_object(self.root / "workspace_manifest.json", "workspace_manifest")
        context = _read_object(self.root / "research_map" / "context.json", "research_context")
        liveness = _read_object(self.root / "lifecycle" / "liveness.json", "research_liveness")
        try:
            manifest = validate_workspace_manifest(manifest, self.root)
        except WorkspaceModeError as exc:
            raise ResearchWebError("invalid_workspace_manifest") from exc
        manifest_root = manifest.get("workspace_root")
        if not isinstance(manifest_root, str) or lexical_path(manifest_root) != self.root:
            raise ResearchWebError("workspace_root_mismatch")
        if manifest.get("workspace_mode") != "research" or context.get("workspace_mode") != "research":
            raise ResearchWebError("research_workspace_mode_required")
        workspace_id = manifest.get("workspace_id")
        if not isinstance(workspace_id, str) or context.get("workspace_id") != workspace_id:
            raise ResearchWebError("research_workspace_id_mismatch")
        if liveness.get("workspace_id") != workspace_id:
            raise ResearchWebError("research_workspace_id_mismatch")
        if context.get("schema_version") != "research_map_context_1":
            raise ResearchWebError("unsupported_research_context_schema")
        if liveness.get("schema_version") != "research_liveness_1":
            raise ResearchWebError("unsupported_research_liveness_schema")
        if manifest.get("state") != "ready":
            raise ResearchWebError("invalid_workspace_state")
        if context.get("lifecycle_state") != "admitted":
            raise ResearchWebError("invalid_research_lifecycle_state")
        if liveness.get("state") != context.get("lifecycle_state"):
            raise ResearchWebError("research_lifecycle_state_mismatch")
        if liveness.get("state") != "admitted":
            raise ResearchWebError("research_lifecycle_state_mismatch")
        revision = context.get("revision")
        if type(revision) is not int or revision < 0 or liveness.get("revision") != revision:
            raise ResearchWebError("research_revision_mismatch")
        missing = [name for name in RESEARCH_CONTEXT_COLLECTIONS if name not in context]
        if missing:
            raise ResearchWebError("research_context_missing_collections: " + ", ".join(missing))
        invalid = [name for name in RESEARCH_CONTEXT_COLLECTIONS if not isinstance(context[name], list)]
        if invalid:
            raise ResearchWebError("research_context_collections_must_be_arrays: " + ", ".join(invalid))
        focus = context.get("focus")
        if not isinstance(focus, dict) or not isinstance(focus.get("claim_ids"), list) or not isinstance(focus.get("node_ids"), list):
            raise ResearchWebError("research_context_focus_invalid")
        self.context = context
        self.created_at = str(context.get("created_at") or manifest.get("created_at") or "")
        if not self.created_at:
            raise ResearchWebError("research_context_created_at_missing")
        self.map_id = str(context.get("map_id") or f"map_{workspace_id}")
        if not self.map_id:
            raise ResearchWebError("research_context_map_id_missing")
        self.revision = revision
        self.nodes = {
            item["id"]: item
            for item in self._collection("nodes")
            if isinstance(item.get("id"), str)
        }

    def _collection(self, name: str) -> list[dict[str, Any]]:
        value = self.context.get(name)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ResearchWebError(f"research_context_{name}_invalid")
        return value

    def progress(self) -> dict[str, int]:
        findings = self._collection("findings")
        nodes = self._collection("nodes")
        return {
            "phase_count": len(self._collection("phases")),
            "claim_count": len(self._collection("claims")),
            "node_count": len(nodes),
            "finding_count": len(findings),
            "gate_count": len(self._collection("gates")),
            "closed_node_count": sum(item.get("state") == "closed" for item in nodes),
            "open_issue_count": sum(item.get("kind") == "issue" and item.get("status") == "open" for item in findings),
        }

    def to_dict(self) -> dict[str, Any]:
        focus = self.context.get("focus", {})
        if not isinstance(focus, dict):
            raise ResearchWebError("research_context_focus_invalid")
        claim_ids = focus.get("claim_ids", [])
        node_ids = focus.get("node_ids", [])
        if not isinstance(claim_ids, list) or not isinstance(node_ids, list):
            raise ResearchWebError("research_context_focus_invalid")
        payload = {
            "schema_version": "research-map/1",
            "map_id": self.map_id,
            "title": str(self.context.get("title") or self.root.name or self.map_id),
            "created_at": self.created_at,
            "revision": self.revision,
            "phases": copy.deepcopy(self._collection("phases")),
            "claims": copy.deepcopy(self._collection("claims")),
            "nodes": copy.deepcopy(self._collection("nodes")),
            "findings": copy.deepcopy(self._collection("findings")),
            "gates": copy.deepcopy(self._collection("gates")),
            "lifecycle_actions": copy.deepcopy(self._collection("lifecycle_actions")),
            "claim_relations": copy.deepcopy(self.context.get("claim_relations", [])),
            "focus_claim_ids": list(claim_ids),
            "focus_node_ids": list(node_ids),
            "metadata": copy.deepcopy(self.context.get("metadata", {})),
            "progress": self.progress(),
        }
        if not isinstance(payload["claim_relations"], list) or not isinstance(payload["metadata"], dict):
            raise ResearchWebError("research_context_projection_invalid")
        return payload


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ResearchWebError(f"{label}_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchWebError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise ResearchWebError(f"{label}_invalid")
    return value


def _detail(payload: dict[str, Any], collection: str, identifier: str) -> dict[str, Any]:
    identifier = unquote(identifier)
    if not identifier or "/" in identifier or "\\" in identifier:
        raise ResearchWebError("unsafe research object id")
    record = next((row for row in payload.get(collection, []) if row.get("id") == identifier), None)
    if record is None:
        raise ResearchWebError(f"unknown {collection[:-1]} id: {identifier}")
    return {"schema_version": "research-object-detail/1", "map_id": payload["map_id"], "object": record}


def _read_node_file(source_root: str, relative: str, research_map: Any) -> dict[str, Any]:
    if not relative:
        raise ResearchWebError("missing path")
    normalized = posixpath.normpath(unquote(relative).replace("\\", "/"))
    parts = Path(normalized).parts
    if normalized in {"..", "."} or normalized.startswith("../") or normalized.startswith("/") or len(parts) < 3 or parts[0] != "nodes":
        raise ResearchWebError("file preview is limited to current ResearchNode files")
    node_id = parts[1]
    if node_id not in research_map.nodes:
        raise ResearchWebError("unknown ResearchNode")
    root = lexical_path(source_root)
    path = root / normalized
    if path_has_symlink(root) or has_symlink_component(root, path):
        raise ResearchWebError("file path contains a symbolic link")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ResearchWebError("file not found") from error
    if not stat.S_ISREG(mode):
        raise ResearchWebError("file not found")
    data = path.read_bytes()
    if len(data) > 256 * 1024:
        data = data[:256 * 1024]
    return {"path": normalized, "text": data.decode("utf-8", errors="replace"), "size": path.stat().st_size}


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or WORKSPACE_ID_PATTERN.fullmatch(value) is None:
        raise ResearchWebError(f"unsafe {label} id")
    return value


def _sanitize(message: str, source_root: str) -> str:
    return message.replace(source_root, "<workspace>")[:4000]
