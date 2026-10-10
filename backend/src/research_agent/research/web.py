"""Read-only transport helpers for clients such as CoRAgent Web.

The transport exposes the same memory snapshot and records as Agent tools.
Workspace/catalog envelopes do not create a separate research model.
"""

from __future__ import annotations

from research_agent.foundation.protocol import WORKSPACE_ID_PATTERN

import copy
import json
import posixpath
import re
import stat
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

from research_agent.foundation.path_safety import has_symlink_component, lexical_path, path_has_symlink
from .workspace import WorkspaceModeError, validate_workspace_manifest
from . import retrieval
from .records import workspace

from .workspace_catalog import catalog_for_web, WorkspaceCatalogError



PROVIDER_PROTOCOL = "research-memory-provider/1"
ERROR_SCHEMA = "research-memory-error/1"
WORKSPACE_LIST_SCHEMA = "research-workspace-list/1"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


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
    reader=None,
) -> Any:
    value = _request_object(request)
    catalog = catalog_for_web(state_dir, workspace_roots)
    operation = value["operation"]
    if operation == "catalog":
        return _catalog(catalog)
    if operation == "remove":
        return catalog.remove(_safe_id(value.get("workspace_id"), "workspace"))
    if operation != "route":
        raise ResearchWebError(f"unsupported provider operation: {operation!r}")
    workspace_id = _safe_id(value.get("workspace_id"), "workspace")
    route = value.get("route")
    if not isinstance(route, str) or route.startswith("/") or ".." in route.split("/"):
        raise ResearchWebError("invalid workspace route")
    query = _query_object(value.get("query"))
    try:
        row = catalog.resolve(workspace_id, attach=True)
    except WorkspaceCatalogError as exc:
        raise ResearchWebError(f"unknown or invalid workspace id: {workspace_id}") from exc
    source_root = row.get("source_root")
    if not isinstance(source_root, str) or not source_root:
        raise ResearchWebError(f"workspace {workspace_id} has no registered location")
    # Registry lookup is canonical-only. The resolved row carries the immutable
    # manifest identity through every response envelope.
    return _route({**row, "source_root": source_root}, route.strip("/"), query, reader=reader)


def register_sources(
    state_dir: str | Path,
    source_roots: Sequence[str | Path],
    labels: Sequence[str] | None = None,
    *, workspace_roots: Sequence[str | Path] | None = None,
) -> list[dict[str, str]]:
    return catalog_for_web(state_dir, workspace_roots).register(list(source_roots), list(labels or []))


def provider_success_payload(request_id: str, payload: Any) -> dict[str, Any]:
    return {"schema_version": PROVIDER_PROTOCOL, "request_id": request_id, "ok": True, "payload": payload}


def provider_error_payload(request_id: str, error: Exception, *, retryable: bool | None = None) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_PROTOCOL,
        "request_id": request_id,
        "ok": False,
        "error": {
            "schema_version": ERROR_SCHEMA,
            "error": str(error)[:4000] or "Research memory provider error",
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


def _catalog(catalog) -> dict[str, Any]:
    # Listing never loads the research journal; the route response supplies live progress.
    summaries = [{"workspace_id": row["workspace_id"], "label": row["label"],
                  "available": True, "valid": None, "progress": {}}
                 for row in catalog.list()]
    available = [row for row in summaries if row["available"]]
    return {
        "schema_version": WORKSPACE_LIST_SCHEMA,
        "default_workspace": available[0]["workspace_id"] if available else (summaries[0]["workspace_id"] if summaries else None),
        "workspaces": summaries,
    }


def _route(row: dict[str, Any], route: str, query: dict[str, str], *, reader=None) -> Any:
    root = row["source_root"]
    runtime_read = reader or _memory_read
    if route in {"", "snapshot"}:
        return {"schema_version": "research-memory-response/1",
                "workspace": {"workspace_id": row["workspace_id"], "label": row.get("label", row["workspace_id"])},
                "snapshot": runtime_read(root)}
    if route == "nodes":
        return retrieval.search(root, kind="node", query=query.get("query", ""), offset=int(query.get("offset", 0)), limit=int(query.get("limit", 20)))
    if route == "records":
        return retrieval.search(root, query=query.get("query", ""), origin=query.get("origin"), node_id=query.get("node_id"), kind=query.get("kind"),
                               after_sequence=int(query.get("after_sequence", 0)),
                               offset=int(query.get("offset", 0)), limit=int(query.get("limit", 20)))
    if route.startswith("record/"):
        return runtime_read(root, ref=route[7:], offset=int(query.get("offset", 0)), limit=int(query.get("limit", 16000)))
    if route.startswith("artifact/"):
        from research_agent.artifacts import PayloadStore
        from research_agent.artifacts.registry import read_manifest
        workspace(root)
        artifact_id = route[9:]
        manifest = read_manifest(root, artifact_id)
        data = PayloadStore(Path(root) / "artifacts").read_bytes(artifact_id)
        offset, limit = int(query.get("offset", 0)), int(query.get("limit", 16000))
        if offset < 0 or not 1 <= limit <= 64000:
            raise ResearchWebError("invalid artifact bounds")
        return {"manifest": manifest, "content": data[offset:offset + limit].decode("utf-8", errors="replace"),
                "next_offset": offset + limit if offset + limit < len(data) else None}
    raise ResearchWebError(f"unknown workspace route: {route}")


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or WORKSPACE_ID_PATTERN.fullmatch(value) is None:
        raise ResearchWebError(f"unsafe {label} id")
    return value


def _sanitize(message: str, source_root: str) -> str:
    return message.replace(source_root, "<workspace>")[:4000]


def _memory_read(root, *, ref=None, **kwargs):
    from research_agent.foundation.transactions import TransactionCoordinator
    from .views import build_snapshot
    with TransactionCoordinator(root).locked():
        workspace(root)
        return retrieval.read(root, ref=ref, **kwargs) if ref else build_snapshot(root)
