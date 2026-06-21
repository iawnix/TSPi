"""Small read-only HTTP server for the workspace explorer."""

from __future__ import annotations

import json
import posixpath
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .normalize import (
    explorer_graph_payload,
    explorer_job_payload,
    explorer_node_payload,
    explorer_workspace_summary,
    normalize_workspace,
)
from .registry import ensure_state_dir, find_workspace, list_workspaces, register_workspace

MAX_TEXT_BYTES = 1_000_000
STATIC_PACKAGE = __package__ or "ts_web"


def _static_asset(name: str):
    return files(STATIC_PACKAGE).joinpath("static", name)


def serve(host: str, port: int, state_dir: str | Path, *, source_root: str | Path | None = None, label: str | None = None) -> None:
    server = create_server(host, port, state_dir, source_root=source_root, label=label)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def create_server(
    host: str,
    port: int,
    state_dir: str | Path,
    *,
    source_root: str | Path | None = None,
    label: str | None = None,
) -> ThreadingHTTPServer:
    if source_root is not None:
        register_workspace(source_root, state_dir, label)
    state = ensure_state_dir(state_dir, source_root=source_root)
    handler = _make_handler(state)
    return ThreadingHTTPServer((host, port), handler)


def _make_handler(state_dir: Path):
    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "TSWeb/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path in {"/", "/index.html"}:
                    self._send_static_file("index.html", "text/html; charset=utf-8")
                elif path == "/api/health":
                    self._send_json({"ok": True})
                elif path == "/api/workspaces":
                    self._send_json(_workspaces_payload(state_dir))
                elif path == "/api/workspace":
                    query = parse_qs(parsed.query)
                    workspace_id = _first(query.get("id"))
                    self._send_json(_workspace_payload(state_dir, workspace_id))
                elif path.startswith("/api/workspace/"):
                    query = parse_qs(parsed.query)
                    workspace_id, rest = _parse_workspace_api_path(path)
                    row = _workspace_row(state_dir, workspace_id)
                    self._send_json(_workspace_route(row, rest, query))
                elif path == "/api/job":
                    row = _workspace_row(state_dir, None)
                    self._send_json(explorer_job_payload(row["source_root"], label=row.get("label"), workspace=row))
                elif path == "/api/tree":
                    row = _workspace_row(state_dir, None)
                    self._send_json(explorer_graph_payload(row["source_root"], label=row.get("label")))
                elif path == "/api/mechanism":
                    row = _workspace_row(state_dir, None)
                    self._send_json(_read_json(row, "mechanism_model.json"))
                elif path == "/api/evidence":
                    row = _workspace_row(state_dir, None)
                    self._send_json(_read_json(row, "evidence_registry.json"))
                elif path.startswith("/api/node/"):
                    row = _workspace_row(state_dir, None)
                    node_id, rest = _parse_node_api_path(path)
                    if rest:
                        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        self._send_json(explorer_node_payload(row["source_root"], node_id, label=row.get("label")))
                elif path == "/api/file":
                    query = parse_qs(parsed.query)
                    row = _workspace_row(state_dir, None)
                    self._send_json(_read_workspace_file(row, _first(query.get("path")) or ""))
                else:
                    self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static_file(self, name: str, content_type: str) -> None:
            body = _static_asset(name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ExplorerHandler


def _workspaces_payload(state_dir: Path) -> dict[str, Any]:
    rows = list_workspaces(state_dir)
    summaries = [explorer_workspace_summary(row) for row in rows]
    return {
        "default_workspace": summaries[0]["id"] if len(summaries) == 1 else "",
        "workspaces": summaries,
    }


def _workspace_payload(state_dir: Path, workspace_id: str | None) -> dict[str, Any]:
    row = _workspace_row(state_dir, workspace_id)
    return {"workspace": row, "view": normalize_workspace(row["source_root"], label=row.get("label"))}


def _workspace_row(state_dir: Path, workspace_id: str | None) -> dict[str, Any]:
    rows = list_workspaces(state_dir)
    if workspace_id is None:
        if not rows:
            raise ValueError("no workspace is registered")
        if len(rows) > 1:
            raise ValueError("multiple workspaces are registered; choose a workspace id")
        return _normalize_workspace_row(rows[0])
    _assert_safe_id(workspace_id, "workspace")
    row = find_workspace(state_dir, workspace_id)
    if row is None:
        raise ValueError(f"unknown workspace id: {workspace_id}")
    return _normalize_workspace_row(row)


def _normalize_workspace_row(row: dict[str, Any]) -> dict[str, Any]:
    workspace_id = row.get("workspace_id") or row.get("id")
    source_root = row.get("source_root") or row.get("source")
    label = row.get("label") or row.get("name") or workspace_id
    if not workspace_id:
        raise ValueError("workspace row is missing an id")
    if not source_root:
        raise ValueError(f"workspace {workspace_id} is missing source_root")
    return {**row, "workspace_id": workspace_id, "source_root": source_root, "label": label}


def _workspace_route(row: dict[str, Any], rest: str, query: dict[str, list[str]]) -> Any:
    source_root = row["source_root"]
    label = row.get("label")
    if rest in {"", "job"}:
        return explorer_job_payload(source_root, label=label, workspace=row)
    if rest == "tree":
        return explorer_graph_payload(source_root, label=label)
    if rest == "mechanism":
        return _read_json(row, "mechanism_model.json")
    if rest == "evidence":
        return _read_json(row, "evidence_registry.json")
    if rest == "file":
        return _read_workspace_file(row, _first(query.get("path")) or "")
    if rest.startswith("node/"):
        node_id, node_rest = _parse_node_rest(rest)
        if node_rest in {"", "detail"}:
            return explorer_node_payload(source_root, node_id, label=label)
        if node_rest == "files":
            return explorer_node_payload(source_root, node_id, label=label)["files"]
        if node_rest.startswith("markdown/"):
            name = node_rest.split("/", 1)[1]
            payload = explorer_node_payload(source_root, node_id, label=label)
            return {"node_id": node_id, "name": name, "text": payload["markdown"].get(name, "")}
    raise ValueError(f"unknown workspace route: {rest}")


def _read_json(row: dict[str, Any], name: str) -> dict[str, Any]:
    path = Path(row["source_root"]) / name
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_read_error": str(exc)}
    return payload if isinstance(payload, dict) else {"_read_error": "JSON root is not an object"}


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
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {rel_path}")
    size = path.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise ValueError(f"file is larger than {MAX_TEXT_BYTES} bytes")
    return {
        "path": path.relative_to(root).as_posix(),
        "text": path.read_text(encoding="utf-8", errors="replace"),
        "size": size,
    }


def _parse_workspace_api_path(path: str) -> tuple[str, str]:
    rest = path[len("/api/workspace/") :]
    parts = rest.split("/", 1)
    workspace_id = unquote(parts[0])
    _assert_safe_id(workspace_id, "workspace")
    return workspace_id, parts[1] if len(parts) > 1 else ""


def _parse_node_api_path(path: str) -> tuple[str, str]:
    rest = path[len("/api/node/") :]
    parts = rest.split("/", 1)
    node_id = unquote(parts[0])
    _assert_safe_id(node_id, "node")
    return node_id, parts[1] if len(parts) > 1 else ""


def _parse_node_rest(rest: str) -> tuple[str, str]:
    node_rest = rest[len("node/") :]
    parts = node_rest.split("/", 1)
    node_id = unquote(parts[0])
    _assert_safe_id(node_id, "node")
    return node_id, parts[1] if len(parts) > 1 else ""


def _assert_safe_id(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"unsafe {label} id: {value!r}")


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]
