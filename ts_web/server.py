"""Small read-only HTTP server for the workspace explorer."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .normalize import normalize_workspace
from .registry import ensure_state_dir, find_workspace, list_workspaces, register_workspace

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
                    self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                elif path == "/api/health":
                    self._send_json({"ok": True})
                elif path == "/api/workspaces":
                    self._send_json({"workspaces": list_workspaces(state_dir)})
                elif path == "/api/workspace":
                    query = parse_qs(parsed.query)
                    workspace_id = _first(query.get("id"))
                    self._send_json(_workspace_payload(state_dir, workspace_id))
                else:
                    self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
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

    return ExplorerHandler


def _workspace_payload(state_dir: Path, workspace_id: str | None) -> dict[str, Any]:
    rows = list_workspaces(state_dir)
    if workspace_id is None:
        if not rows:
            raise ValueError("no workspace is registered")
        row = rows[0]
    else:
        row = find_workspace(state_dir, workspace_id)
        if row is None:
            raise ValueError(f"unknown workspace id: {workspace_id}")
    return {"workspace": row, "view": normalize_workspace(row["source_root"], label=row.get("label"))}


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]
