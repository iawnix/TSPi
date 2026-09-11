"""Read-only HTTP transport for the independent TS Web component."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from .provider import ProviderClient, ProviderClientError
from .reloader import ReleaseWatcher


STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "i18n.js": "text/javascript; charset=utf-8",
    "logo.svg": "image/svg+xml",
    "favicon.svg": "image/svg+xml",
    "research-tree.js": "text/javascript; charset=utf-8",
    "research-map.js": "text/javascript; charset=utf-8",
    "claim-map.js": "text/javascript; charset=utf-8",
    "attempt-timeline.js": "text/javascript; charset=utf-8",
}
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


def serve(
    host: str,
    port: int,
    state_dir: str | Path,
    *,
    provider_command: str | Path | Sequence[str],
    workspace_roots: Sequence[str | Path] | None = None,
    release_entrypoint: str | Path | None = None,
    loaded_entrypoint: str | Path | None = None,
    release_poll_interval: float = 1.0,
) -> bool:
    client = ProviderClient(provider_command, state_dir, workspace_roots=workspace_roots)
    server = create_server(host, port, state_dir, provider=client)
    watcher = None
    if release_entrypoint is not None:
        watcher = ReleaseWatcher(
            release_entrypoint,
            loaded_entrypoint=loaded_entrypoint,
            poll_interval=release_poll_interval,
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
    provider: ProviderClient,
) -> ThreadingHTTPServer:
    # The provider owns state directory validation and all workspace locations.
    client = provider
    return ThreadingHTTPServer((host, port), _make_handler(client))


def _make_handler(provider: ProviderClient):
    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "TSWeb/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path in {"/", "/index.html"}:
                    self._send_static("index.html")
                    return
                if parsed.path in {f"/{name}" for name in STATIC_FILES if name != "index.html"}:
                    self._send_static(parsed.path.removeprefix("/"))
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        {
                            "ok": True,
                            "protocol": "ts-research-kernel/6",
                            "projection_protocol": "ts-web-workspace/6",
                            "graph_protocol": "ts-explorer-graph/6",
                            "provider_protocol": "ts-web-provider/1",
                            "read_only": True,
                        }
                    )
                    return
                if parsed.path == "/api/workspaces":
                    self._send_json(provider.request("catalog"))
                    return
                if parsed.path.startswith("/api/workspace/"):
                    workspace_id, route = _parse_workspace_path(parsed.path)
                    query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
                    self._send_json(
                        provider.request("route", workspace_id=workspace_id, route=route, query=query)
                    )
                    return
                self._send_error("unknown route", status=HTTPStatus.NOT_FOUND)
            except ProviderClientError as error:
                self._send_error(str(error), status=HTTPStatus.BAD_REQUEST, retryable=error.retryable)
            except (OSError, ValueError) as error:
                self._send_error(str(error), status=HTTPStatus.BAD_REQUEST)
            except Exception as error:  # noqa: BLE001 - the HTTP boundary always emits a bounded record
                self._send_error(str(error), status=HTTPStatus.INTERNAL_SERVER_ERROR, retryable=True)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_static(self, name: str) -> None:
            if name not in STATIC_FILES:
                self._send_error("unknown static asset", status=HTTPStatus.NOT_FOUND)
                return
            path = STATIC_ROOT / name
            if not path.is_file() or path.is_symlink():
                self._send_error("static asset is unavailable", status=HTTPStatus.NOT_FOUND)
                return
            self._send_body(path.read_bytes(), content_type=STATIC_FILES[name])

        def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            self._send_body(body, status=status, content_type="application/json; charset=utf-8")

        def _send_error(
            self,
            message: str,
            *,
            status: HTTPStatus,
            retryable: bool = False,
        ) -> None:
            self._send_json(
                {
                    "schema_version": "ts-web-error/1",
                    "error": message[:4000],
                    "retryable": retryable,
                },
                status=status,
            )

        def _send_body(
            self,
            body: bytes,
            *,
            status: HTTPStatus = HTTPStatus.OK,
            content_type: str,
        ) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

    return ExplorerHandler


def _parse_workspace_path(path: str) -> tuple[str, str]:
    tail = path.removeprefix("/api/workspace/")
    parts = tail.split("/", 1)
    workspace_id = unquote(parts[0])
    if not workspace_id or workspace_id in {".", ".."} or "/" in workspace_id or "\\" in workspace_id:
        raise ValueError("unsafe workspace id")
    return workspace_id, parts[1].strip("/") if len(parts) > 1 else ""
