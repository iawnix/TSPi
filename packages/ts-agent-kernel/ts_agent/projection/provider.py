"""Versioned read-only provider boundary for the optional TS Web component."""

from __future__ import annotations

import posixpath
import stat
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

from ts_agent.workspace.path_safety import has_symlink_component, lexical_path, path_has_symlink

from . import file_preview as projection_file_preview
from . import normalize as projection
from .registry import (
    ensure_state_dir,
    find_workspace,
    list_workspaces,
    reconcile_workspace_registry,
    remove_workspace,
    register_workspaces,
    workspace_discovery_roots,
)


PROVIDER_PROTOCOL = "ts-web-provider/1"
WORKSPACE_LIST_SCHEMA = "ts-explorer-workspace-list/1"


class ProviderRequestError(ValueError):
    """A client request cannot be served by the core provider."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def handle_request(
    state_dir: str | Path,
    request: object,
    *,
    workspace_roots: Sequence[str | Path] | None = None,
) -> Any:
    """Handle one JSON-lines provider request without exposing physical paths."""

    value = _request_object(request)
    operation = value.get("operation")
    state = ensure_state_dir(state_dir)
    roots = workspace_discovery_roots(state, workspace_roots)
    reconcile_workspace_registry(state, roots)
    if operation == "catalog":
        return _workspaces_payload(state)
    if operation == "remove":
        workspace_id = _safe_id(value.get("workspace_id"), "workspace")
        return remove_workspace(state, workspace_id)
    if operation != "route":
        raise ProviderRequestError(f"unsupported provider operation: {operation!r}")

    workspace_id = _safe_id(value.get("workspace_id"), "workspace")
    route = value.get("route")
    if not isinstance(route, str) or route.startswith("/") or ".." in route.split("/"):
        raise ProviderRequestError("invalid workspace route")
    row = _workspace_row(state, workspace_id)
    query = _query_object(value.get("query"))
    return _workspace_route(row, route.strip("/"), query)


def register_sources(
    state_dir: str | Path,
    source_roots: Sequence[str | Path],
    labels: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Register source locations on behalf of a local TS Web CLI invocation."""

    return register_workspaces(list(source_roots), state_dir, list(labels or []))


def provider_error_payload(
    request_id: str,
    error: Exception,
    *,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_PROTOCOL,
        "request_id": request_id,
        "ok": False,
        "error": {
            "schema_version": "ts-web-error/1",
            "error": str(error)[:4000],
            "retryable": bool(getattr(error, "retryable", False) if retryable is None else retryable),
        },
    }


def provider_success_payload(request_id: str, payload: Any) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_PROTOCOL,
        "request_id": request_id,
        "ok": True,
        "payload": payload,
    }


def _request_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderRequestError("provider request must be an object")
    expected = {"schema_version", "request_id", "operation", "workspace_id", "route", "query"}
    if set(value) - expected:
        raise ProviderRequestError("provider request contains unsupported fields")
    if value.get("schema_version") != "ts-web-provider-request/1":
        raise ProviderRequestError("unsupported provider request schema")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 160:
        raise ProviderRequestError("provider request_id must be a bounded string")
    return value


def _query_object(value: object) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderRequestError("provider query must be an object")
    query: dict[str, list[str]] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str) or len(key) > 80 or len(item) > 4096:
            raise ProviderRequestError("provider query values must be bounded strings")
        query[key] = [item]
    return query


def _workspaces_payload(state_dir: Path) -> dict[str, Any]:
    summaries = [_workspace_catalog_summary(row) for row in list_workspaces(state_dir)]
    available = [row for row in summaries if row["available"]]
    return {
        "schema_version": WORKSPACE_LIST_SCHEMA,
        "default_workspace": (
            available[0]["workspace_id"]
            if available
            else summaries[0]["workspace_id"]
            if summaries
            else None
        ),
        "workspaces": summaries,
    }


def _workspace_catalog_summary(row: dict[str, Any]) -> dict[str, Any]:
    source_root = str(row.get("source_root") or "")
    workspace_id = str(row.get("workspace_id") or "")
    label = str(row.get("label") or (Path(source_root).name if source_root else workspace_id))
    try:
        return projection.workspace_summary(row)
    except Exception as error:  # noqa: BLE001 - one unavailable workspace must not break the catalog
        return {
            "workspace_id": workspace_id,
            "label": label,
            "available": False,
            "load_error": _sanitize_error(str(error), source_root),
            "kernel_protocol": None,
            "workspace_revision": None,
            "valid": False,
            "claim_count": 0,
            "phase_count": 0,
            "node_count": 0,
            "open_node_count": 0,
            "open_finding_count": 0,
            "focus_claim_refs": [],
            "focus_node_refs": [],
            "acceptance_record_count": 0,
            "current_acceptance_count": 0,
        }


def _workspace_row(state_dir: Path, workspace_id: str) -> dict[str, Any]:
    row = find_workspace(state_dir, workspace_id)
    if row is None:
        raise ProviderRequestError(f"unknown workspace id: {workspace_id}")
    source_root = row.get("source_root")
    if not isinstance(source_root, str) or not source_root:
        raise ProviderRequestError(f"workspace {workspace_id} has no registered location")
    return {**row, "workspace_id": workspace_id, "source_root": source_root, "label": row.get("label") or workspace_id}


def _workspace_route(row: dict[str, Any], route: str, query: dict[str, list[str]]) -> Any:
    source_root = row["source_root"]
    label = row.get("label")
    if route == "":
        view = projection.normalize_workspace(source_root, label=label)
        return {"workspace": projection.workspace_summary(row, view=view), "view": view}
    if route == "snapshot":
        return projection.workspace_snapshot(
            row,
            since_workspace_revision=_first(query.get("workspace_revision")),
            since_operational_revision=_first(query.get("operational_revision")),
        )
    if route == "graph":
        return projection.graph_payload(source_root, label=label)
    if route == "claims":
        view = projection.normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-claims/1", "claims": view["claims"], "claim_relations": view["claim_relations"]}
    if route == "phases":
        view = projection.normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-research-phases/1", "research_phases": view["research_phases"]}
    if route == "nodes":
        view = projection.normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-research-nodes/1", "research_nodes": view["research_nodes"]}
    if route == "observations":
        view = projection.normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-observations/1", "observations": view["observations"]}
    if route == "validation":
        view = projection.normalize_workspace(source_root, label=label)
        return {
            "schema_version": "ts-explorer-validation/1",
            "proof_specs": view["proof_specs"],
            "validation_results": view["validation_results"],
            "acceptances": view["acceptances"],
            "current_acceptances": view["current_acceptances"],
            "acceptance_summary": view["acceptance_summary"],
        }
    if route == "findings":
        view = projection.normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-findings/1", "findings": view["findings"]}
    if route == "files":
        return projection.research_files_payload(source_root, _first(query.get("query")) or "")
    if route == "activity":
        view = projection.normalize_workspace(source_root, label=label)
        return {
            "schema_version": "ts-explorer-activity/1",
            "operational_revision": view["operational_revision"],
            "operational_summary": view["operational_summary"],
            "deterministic_activities": view["deterministic_activities"],
            "activity_summaries": view["activity_summaries"],
            "node_dispatch": view.get("node_dispatch", []),
            "activity_integrity_findings": view["activity_integrity_findings"],
            "operational_integrity_findings": view.get("operational_integrity_findings", []),
            "calculation_attempt_integrity_findings": view["calculation_attempt_integrity_findings"],
            "agent_runs": view["agent_runs"],
            "pending_review_dispositions": view["pending_review_dispositions"],
            "pending_controls": view["pending_controls"],
            "unresolved_controls": view["unresolved_controls"],
            "retryable_controls": view["retryable_controls"],
        }
    if route == "file":
        return _read_workspace_file(row, _first(query.get("path")) or "")
    if route.startswith("claim/"):
        return projection.claim_payload(source_root, _detail_id(route, "claim"), label=label)
    if route.startswith("node/"):
        return projection.node_payload(source_root, _detail_id(route, "node"), label=label)
    raise ProviderRequestError(f"unknown workspace route: {route}")


def _read_workspace_file(row: dict[str, Any], rel_path: str) -> dict[str, Any]:
    if not rel_path:
        raise ProviderRequestError("missing path")
    root = lexical_path(row["source_root"])
    if path_has_symlink(root) or not root.is_dir():
        raise ProviderRequestError("workspace root is not a readable physical directory", retryable=True)
    normalized = posixpath.normpath(unquote(rel_path).replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ProviderRequestError("unsafe file path")
    path = root / normalized
    if has_symlink_component(root, path):
        raise ProviderRequestError("file path contains a symbolic link")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ProviderRequestError("file not found") from error
    except OSError as error:
        raise ProviderRequestError("cannot inspect file", retryable=True) from error
    if not stat.S_ISREG(mode):
        raise ProviderRequestError("file not found")
    parts = Path(normalized).parts
    if len(parts) < 3 or parts[0] != "nodes":
        raise ProviderRequestError("file preview is limited to current ResearchNode files")
    allowed = {
        item["path"]
        for item in projection.list_node_files(root, parts[1])["files"]
        if isinstance(item.get("path"), str)
    }
    if normalized not in allowed:
        raise ProviderRequestError("file preview is limited to current ResearchNode files")
    return {"path": normalized, "text": projection_file_preview.read_text_preview(path), "size": path.stat().st_size}


def _detail_id(route: str, kind: str) -> str:
    prefix = f"{kind}/"
    identifier = unquote(route.removeprefix(prefix))
    if "/" in identifier:
        raise ProviderRequestError(f"unknown {kind} route")
    return _safe_id(identifier, kind)


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ProviderRequestError(f"unsafe {label} id")
    return value


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _sanitize_error(message: str, source_root: str) -> str:
    return message.replace(source_root, "<workspace>").replace("source_root", "workspace location")[:4000]
