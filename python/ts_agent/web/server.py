"""Small read-only HTTP server for the research explorer."""

from __future__ import annotations

import json
import posixpath
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from .file_preview import MAX_TEXT_BYTES, read_text_preview
from .normalize import (
    claim_payload,
    graph_payload,
    list_node_files,
    node_payload,
    normalize_workspace,
    research_files_payload,
    workspace_snapshot,
    workspace_summary,
)
from .registry import (
    ensure_state_dir,
    find_workspace,
    list_workspaces,
    reconcile_workspace_registry,
    register_workspace,
    workspace_discovery_roots,
)
from .reloader import ReleaseWatcher

STATIC_PACKAGE = __package__ or "ts_agent.web"


class RouteNotFound(ValueError):
    """Raised for an unknown read-only API route."""


def _static_asset(name: str):
    return files(STATIC_PACKAGE).joinpath("static", name)


def serve(
    host: str,
    port: int,
    state_dir: str | Path,
    *,
    source_root: str | Path | None = None,
    label: str | None = None,
    workspace_roots: Sequence[str | Path] | None = None,
    release_entrypoint: str | Path | None = None,
    loaded_entrypoint: str | Path | None = None,
    release_poll_interval: float = 1.0,
    release_ready: Callable[[Path], bool] | None = None,
) -> bool:
    """Serve until stopped, returning true when a selected release changed."""

    server = create_server(
        host,
        port,
        state_dir,
        source_root=source_root,
        label=label,
        workspace_roots=workspace_roots,
    )
    watcher = None
    if release_entrypoint is not None:
        watcher = ReleaseWatcher(
            release_entrypoint,
            loaded_entrypoint=loaded_entrypoint,
            poll_interval=release_poll_interval,
            ready=release_ready,
        )
        watcher.start(server.shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if watcher is not None:
            watcher.stop()
    return bool(watcher and watcher.restart_requested)


def create_server(
    host: str,
    port: int,
    state_dir: str | Path,
    *,
    source_root: str | Path | None = None,
    label: str | None = None,
    workspace_roots: Sequence[str | Path] | None = None,
) -> ThreadingHTTPServer:
    if source_root is not None:
        register_workspace(source_root, state_dir, label)
    state = ensure_state_dir(state_dir, source_root=source_root)
    discovery_roots = workspace_discovery_roots(state, workspace_roots)
    reconcile_workspace_registry(state, discovery_roots)
    return ThreadingHTTPServer((host, port), _make_handler(state, discovery_roots))


def _make_handler(state_dir: Path, workspace_roots: Sequence[Path]):
    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "TSWeb/5.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path in {"/", "/index.html"}:
                    self._send_static_file("index.html", "text/html; charset=utf-8")
                    return
                if parsed.path == "/app.css":
                    self._send_static_file("app.css", "text/css; charset=utf-8")
                    return
                if parsed.path == "/app.js":
                    self._send_static_file("app.js", "text/javascript; charset=utf-8")
                    return
                if parsed.path == "/research-tree.js":
                    self._send_static_file("research-tree.js", "text/javascript; charset=utf-8")
                    return
                if parsed.path == "/claim-map.js":
                    self._send_static_file("claim-map.js", "text/javascript; charset=utf-8")
                    return
                if parsed.path == "/api/health":
                    self._send_json({"ok": True, "protocol": "ts-research-kernel/5", "read_only": True})
                    return
                if parsed.path == "/api/workspaces":
                    reconcile_workspace_registry(state_dir, workspace_roots)
                    self._send_json(_workspaces_payload(state_dir))
                    return
                if parsed.path.startswith("/api/workspace/"):
                    workspace_id, rest = _parse_workspace_api_path(parsed.path)
                    row = _workspace_row(state_dir, workspace_id)
                    self._send_json(_workspace_route(row, rest, parse_qs(parsed.query)))
                    return
                raise RouteNotFound(f"unknown route: {parsed.path}")
            except RouteNotFound as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static_file(self, name: str, content_type: str) -> None:
            body = _static_asset(name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ExplorerHandler


def _workspaces_payload(state_dir: Path) -> dict[str, Any]:
    summaries = [_workspace_catalog_summary(row) for row in list_workspaces(state_dir)]
    available = [row for row in summaries if row["available"]]
    return {
        "schema_version": "ts-explorer-workspace-list/1",
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
    try:
        return workspace_summary(row)
    except Exception as exc:  # noqa: BLE001 - one bad workspace must not break the catalog
        source_root = str(row.get("source_root") or "")
        workspace_id = str(row.get("workspace_id") or "")
        return {
            **row,
            "workspace_id": workspace_id,
            "label": str(row.get("label") or (Path(source_root).name if source_root else workspace_id)),
            "source_root": source_root,
            "available": False,
            "load_error": str(exc),
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
    _assert_safe_id(workspace_id, "workspace")
    row = find_workspace(state_dir, workspace_id)
    if row is None:
        raise ValueError(f"unknown workspace id: {workspace_id}")
    source_root = row.get("source_root")
    if not source_root:
        raise ValueError(f"workspace {workspace_id} is missing source_root")
    return {
        **row,
        "workspace_id": workspace_id,
        "source_root": source_root,
        "label": row.get("label") or workspace_id,
    }


def _workspace_route(row: dict[str, Any], rest: str, query: dict[str, list[str]]) -> Any:
    source_root = row["source_root"]
    label = row.get("label")
    if rest == "":
        view = normalize_workspace(source_root, label=label)
        return {"workspace": workspace_summary(row, view=view), "view": view}
    if rest == "snapshot":
        return workspace_snapshot(
            row,
            since_workspace_revision=_first(query.get("workspace_revision")),
            since_operational_revision=_first(query.get("operational_revision")),
        )
    if rest == "graph":
        return graph_payload(source_root, label=label)
    if rest == "claims":
        view = normalize_workspace(source_root, label=label)
        return {
            "schema_version": "ts-explorer-claims/1",
            "claims": view["claims"],
            "claim_relations": view["claim_relations"],
        }
    if rest == "phases":
        view = normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-research-phases/1", "research_phases": view["research_phases"]}
    if rest == "nodes":
        view = normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-research-nodes/1", "research_nodes": view["research_nodes"]}
    if rest == "observations":
        view = normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-observations/1", "observations": view["observations"]}
    if rest == "validation":
        view = normalize_workspace(source_root, label=label)
        return {
            "schema_version": "ts-explorer-validation/1",
            "validation_specs": view["validation_specs"],
            "validation_results": view["validation_results"],
            "acceptances": view["acceptances"],
            "current_acceptances": view["current_acceptances"],
            "acceptance_summary": view["acceptance_summary"],
        }
    if rest == "findings":
        view = normalize_workspace(source_root, label=label)
        return {"schema_version": "ts-explorer-findings/1", "findings": view["findings"]}
    if rest == "files":
        return research_files_payload(source_root, _first(query.get("query")) or "")
    if rest == "activity":
        view = normalize_workspace(source_root, label=label)
        return {
            "schema_version": "ts-explorer-activity/1",
            "operational_revision": view["operational_revision"],
            "operational_summary": view["operational_summary"],
            "deterministic_activities": view["deterministic_activities"],
            "agent_runs": view["agent_runs"],
            "pending_review_dispositions": view["pending_review_dispositions"],
            "pending_controls": view["pending_controls"],
            "unresolved_controls": view["unresolved_controls"],
        }
    if rest == "file":
        return _read_workspace_file(row, _first(query.get("path")) or "")
    if rest.startswith("claim/"):
        claim_id = _single_detail_id(rest, "claim")
        return claim_payload(source_root, claim_id, label=label)
    if rest.startswith("node/"):
        node_id = _single_detail_id(rest, "node")
        return node_payload(source_root, node_id, label=label)
    raise RouteNotFound(f"unknown workspace route: {rest}")


def _read_workspace_file(row: dict[str, Any], rel_path: str) -> dict[str, Any]:
    if not rel_path:
        raise ValueError("missing path")
    root = Path(row["source_root"]).resolve()
    normalized = posixpath.normpath(unquote(rel_path).replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError(f"unsafe path: {rel_path!r}")
    path = (root / normalized).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"path escapes workspace: {rel_path!r}")
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ValueError(f"file not found: {rel_path}")
    parts = Path(normalized).parts
    if len(parts) < 3 or parts[0] != "nodes":
        raise ValueError("file preview is limited to current ResearchNode files")
    allowed = {
        row["path"]
        for row in list_node_files(root, parts[1])["files"]
        if isinstance(row.get("path"), str)
    }
    if normalized not in allowed:
        raise ValueError("file preview is limited to current ResearchNode files")
    text = read_text_preview(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "text": text,
        "size": path.stat().st_size,
    }


def _parse_workspace_api_path(path: str) -> tuple[str, str]:
    tail = path.removeprefix("/api/workspace/")
    parts = tail.split("/", 1)
    workspace_id = unquote(parts[0])
    _assert_safe_id(workspace_id, "workspace")
    return workspace_id, parts[1].strip("/") if len(parts) > 1 else ""


def _single_detail_id(rest: str, kind: str) -> str:
    prefix = f"{kind}/"
    identifier = unquote(rest.removeprefix(prefix))
    if "/" in identifier:
        raise RouteNotFound(f"unknown {kind} route: {rest}")
    _assert_safe_id(identifier, kind)
    return identifier


def _assert_safe_id(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"unsafe {label} id: {value!r}")


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None
