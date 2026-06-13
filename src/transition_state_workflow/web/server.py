#!/usr/bin/env python3
"""Read-only web explorer for TS-search hypothesis workspaces."""

from __future__ import annotations

import argparse
import json
import mimetypes
import posixpath
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from transition_state_workflow.base.workspace import ExplorerServerConfig, ExplorerWorkspaceConfig
from transition_state_workflow.base.explorer_registry import default_registry_path
from transition_state_workflow.web.assets import read_explorer_index_html
from transition_state_workflow.tool.pathway_model import summarize_pathway_model
from transition_state_workflow.util.cli import configure_cli_logging, emit_json
from transition_state_workflow.util.path_utils import (
    clean_string,
    first_nonempty_string,
    is_path_relative_to,
    list_or_empty,
    slugify_workspace_id,
)

try:
    from transition_state_workflow.tool.normalize_view import normalize_ts_workspace_to_explorer_graph
except Exception:  # pragma: no cover - surfaced at request time
    normalize_ts_workspace_to_explorer_graph = None

try:
    from transition_state_workflow.tool.validate_workspace import validate_ts_workspace_contract
except Exception:  # pragma: no cover - validator is advisory for the web service
    validate_ts_workspace_contract = None

APP_NAME = "TS Hypothesis Explorer"
MAX_TEXT_BYTES = 1_000_000
DEFAULT_PORT = 8765


def main() -> int:
    """Run the explorer inspect or serve command-line interface."""

    parser = argparse.ArgumentParser(
        description="Visualize a tssearch_<system> workspace without modifying it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = sub.add_parser("inspect", help="Validate source and print graph JSON.")
    inspect_cmd.add_argument("--source", required=True, type=Path, help="tssearch workspace root.")
    inspect_cmd.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Explorer state directory. Defaults to /tmp/ts_explorer_state/<source-name>.",
    )
    inspect_cmd.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    inspect_cmd.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    inspect_cmd.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    serve = sub.add_parser("serve", help="Start the local read-only web service.")
    serve.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Single strict-v2 tssearch workspace or mirror root.",
    )
    serve.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Explorer state directory for --source. Must be outside --source unless --allow-source-write is set.",
    )
    serve.add_argument(
        "--workspace-registry",
        type=Path,
        default=None,
        help=(
            "JSON registry of TS explorer workspaces. Reloaded automatically when the "
            "file changes, so new workspaces appear without a restart. When no source, "
            "registry, or root is given, the persistent default registry is used."
        ),
    )
    serve.add_argument(
        "--workspace-root",
        type=Path,
        action="append",
        default=[],
        help="Root to scan for local_mirror/tssearch_* workspaces. May be repeated.",
    )
    serve.add_argument("--default-workspace", default="", help="Workspace id to open by default.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1.")
    serve.add_argument("--port", default=DEFAULT_PORT, type=int, help="Bind port.")
    serve.add_argument(
        "--allow-source-write",
        action="store_true",
        help="Allow state-dir inside source. Not recommended.",
    )
    serve.add_argument(
        "--open-url-file",
        type=Path,
        default=None,
        help="Write the service URL to this file.",
    )
    serve.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    serve.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    args = parser.parse_args()
    configure_cli_logging(verbose=getattr(args, "verbose", False), quiet=getattr(args, "quiet", False))
    if args.command == "inspect":
        workspace = validate_explorer_workspace_config(
            ExplorerWorkspaceConfig(
                workspace_id="inspect",
                display_name=args.source.name,
                source_directory=args.source,
                explorer_state_directory=args.state_dir or default_state_dir_for_source(args.source, "inspect"),
            ),
            False,
        )
        payload = load_explorer_workspace_api_payload(workspace.source_directory, workspace=workspace)
        emit_json(payload, pretty=args.pretty)
        return 0
    if args.command == "serve":
        config = build_explorer_server_config(
            args.source,
            args.state_dir,
            args.host,
            args.port,
            args.allow_source_write,
            workspace_registry=args.workspace_registry,
            workspace_roots=args.workspace_root,
            default_workspace=args.default_workspace,
        )
        return serve_forever(config, open_url_file=args.open_url_file)
    raise SystemExit(f"unsupported command: {args.command}")


def build_explorer_server_config(
    source: Path | None,
    state_dir: Path | None,
    host: str,
    port: int,
    allow_source_workspace_writes: bool,
    *,
    workspace_registry: Path | None = None,
    workspace_roots: list[Path] | None = None,
    default_workspace: str = "",
) -> ExplorerServerConfig:
    """Build server configuration from CLI source, registry, and discovery inputs."""

    workspaces: list[ExplorerWorkspaceConfig] = []
    registry_root = workspace_registry.expanduser().resolve() if workspace_registry else None
    roots = tuple(path.expanduser().resolve() for path in (workspace_roots or []))
    if source is None and registry_root is None and not roots:
        # Long-lived default mode: serve the persistent registry, which may be
        # empty now and gain workspaces later without a server restart.
        registry_root = default_registry_path().resolve()

    if source is not None:
        source_root = source.expanduser().resolve()
        state_root = (
            state_dir.expanduser().resolve()
            if state_dir is not None
            else default_state_dir_for_source(source_root, "default")
        )
        workspaces.append(
            validate_explorer_workspace_config(
                ExplorerWorkspaceConfig(
                    workspace_id="default",
                    display_name=source_root.name,
                    source_directory=source_root,
                    explorer_state_directory=state_root,
                    project_directory=infer_project_dir(source_root),
                    metadata={"mode": "single-source"},
                ),
                allow_source_workspace_writes,
            )
        )
    if registry_root is not None and registry_root.exists():
        workspaces.extend(load_explorer_registry_workspace_configs(registry_root, allow_source_workspace_writes))
    if roots:
        workspaces.extend(discover_explorer_workspace_configs(roots, allow_source_workspace_writes))
    workspaces = deduplicate_explorer_workspace_configs(workspaces)
    if not workspaces and registry_root is None and not roots:
        raise SystemExit("no workspaces configured; pass --source, --workspace-registry, or --workspace-root")
    default_id = clean_string(default_workspace)
    if default_id:
        assert_safe_workspace_id(default_id)
        if default_id not in {workspace.workspace_id for workspace in workspaces}:
            raise SystemExit(f"default workspace not found: {default_id}")
    return ExplorerServerConfig(
        workspaces=tuple(workspaces),
        default_workspace_id=default_id,
        bind_host=host,
        bind_port=int(port),
        allow_source_workspace_writes=bool(allow_source_workspace_writes),
        workspace_registry_path=registry_root,
        workspace_discovery_roots=roots,
    )


def default_state_dir_for_source(source: Path, workspace_id: str) -> Path:
    """Return the default external state directory for one workspace."""

    return Path("/tmp") / "ts_explorer_state" / workspace_id / source.name


class ExplorerWorkspaceDirectory:
    """Live view of configured workspaces with registry hot-reload.

    CLI --source and --workspace-root workspaces are fixed for the life of the
    process. Registry workspaces are re-read whenever the registry file's mtime
    changes, so a long-lived service picks up newly registered TS searches
    without a restart.
    """

    def __init__(self, config: ExplorerServerConfig) -> None:
        """Capture static workspaces and prepare registry reload state."""

        self._config = config
        self._lock = threading.Lock()
        self._static_workspaces = tuple(
            workspace
            for workspace in config.workspaces
            if clean_string((workspace.metadata or {}).get("origin")) != "registry"
        )
        self._registry_workspaces: tuple[ExplorerWorkspaceConfig, ...] = tuple(
            workspace
            for workspace in config.workspaces
            if clean_string((workspace.metadata or {}).get("origin")) == "registry"
        )
        self._registry_mtime_ns = self._registry_mtime()

    def _registry_mtime(self) -> int:
        """Return the registry file mtime in nanoseconds, or -1 when absent."""

        path = self._config.workspace_registry_path
        if path is None:
            return -1
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return -1

    def _reload_registry_if_changed(self) -> None:
        """Re-read registry workspaces when the file changed since last read."""

        path = self._config.workspace_registry_path
        if path is None:
            return
        current = self._registry_mtime()
        if current == self._registry_mtime_ns:
            return
        try:
            reloaded = load_explorer_registry_workspace_configs(
                path, self._config.allow_source_workspace_writes
            )
        except (SystemExit, OSError, ValueError) as exc:
            sys.stderr.write(f"workspace registry reload failed, keeping previous list: {exc}\n")
            self._registry_mtime_ns = current
            return
        self._registry_workspaces = tuple(reloaded)
        self._registry_mtime_ns = current

    def current_workspaces(self) -> tuple[ExplorerWorkspaceConfig, ...]:
        """Return the deduplicated live workspace list."""

        with self._lock:
            self._reload_registry_if_changed()
            merged = list(self._static_workspaces) + list(self._registry_workspaces)
        return tuple(deduplicate_explorer_workspace_configs(merged))

    def default_workspace_id(self) -> str:
        """Return the configured or first available workspace id."""

        configured = clean_string(self._config.default_workspace_id)
        workspaces = self.current_workspaces()
        if configured and any(workspace.workspace_id == configured for workspace in workspaces):
            return configured
        return workspaces[0].workspace_id if workspaces else ""

    def get_by_id(self, workspace_id: str) -> ExplorerWorkspaceConfig:
        """Find a live workspace by id or raise an HTTP error."""

        assert_safe_workspace_id(workspace_id)
        for workspace in self.current_workspaces():
            if workspace.workspace_id == workspace_id:
                return workspace
        raise HTTPError(HTTPStatus.NOT_FOUND, "workspace_not_found", f"Workspace not found: {workspace_id}")

    def get_default(self) -> ExplorerWorkspaceConfig:
        """Return the default workspace or raise an HTTP error when none exist."""

        default_id = self.default_workspace_id()
        if not default_id:
            raise HTTPError(
                HTTPStatus.NOT_FOUND,
                "no_workspaces",
                "No workspaces are registered yet; register one and reload.",
            )
        return self.get_by_id(default_id)


def validate_explorer_workspace_config(
    workspace: ExplorerWorkspaceConfig,
    allow_source_workspace_writes: bool,
) -> ExplorerWorkspaceConfig:
    """Resolve and validate one explorer workspace configuration."""

    assert_safe_workspace_id(workspace.workspace_id)
    source_root = workspace.source_directory.expanduser().resolve()
    state_root = workspace.explorer_state_directory.expanduser().resolve()
    project_root = workspace.project_directory.expanduser().resolve() if workspace.project_directory is not None else None
    if not source_root.exists():
        raise SystemExit(f"workspace {workspace.workspace_id} source does not exist: {source_root}")
    if not source_root.is_dir():
        raise SystemExit(f"workspace {workspace.workspace_id} source is not a directory: {source_root}")
    require_workspace(source_root)
    if not allow_source_workspace_writes and is_path_relative_to(state_root, source_root):
        raise SystemExit(
            f"workspace {workspace.workspace_id} state-dir must be outside source to avoid workspace pollution "
            "(or pass --allow-source-write intentionally)."
        )
    state_root.mkdir(parents=True, exist_ok=True)
    return ExplorerWorkspaceConfig(
        workspace_id=workspace.workspace_id,
        display_name=workspace.display_name or workspace.workspace_id,
        source_directory=source_root,
        explorer_state_directory=state_root,
        project_directory=project_root,
        metadata=workspace.metadata or {},
    )


def load_explorer_registry_workspace_configs(
    registry_path: Path,
    allow_source_workspace_writes: bool,
) -> list[ExplorerWorkspaceConfig]:
    """Load workspace definitions from a JSON registry file."""

    if not registry_path.exists():
        raise SystemExit(f"workspace registry does not exist: {registry_path}")
    payload = read_json_required(registry_path)
    raw_items = payload.get("workspaces", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise SystemExit(f"workspace registry must contain a workspaces list: {registry_path}")
    out: list[ExplorerWorkspaceConfig] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise SystemExit(f"workspace registry item {index} is not an object")
        source = clean_string(item.get("source"))
        if not source:
            raise SystemExit(f"workspace registry item {index} missing source")
        workspace_id = clean_string(item.get("id")) or slugify_workspace_id(Path(source).name)
        state_dir = clean_string(item.get("state_dir"))
        project_dir = clean_string(item.get("project_dir"))
        name = clean_string(item.get("name")) or workspace_id
        metadata = {key: value for key, value in item.items() if key not in {"id", "name", "source", "state_dir", "project_dir"}}
        metadata["origin"] = "registry"
        source_path = Path(source)
        try:
            out.append(
                validate_explorer_workspace_config(
                    ExplorerWorkspaceConfig(
                        workspace_id=workspace_id,
                        display_name=name,
                        source_directory=source_path,
                        explorer_state_directory=Path(state_dir) if state_dir else default_state_dir_for_source(source_path.expanduser().resolve(), workspace_id),
                        project_directory=Path(project_dir) if project_dir else infer_project_dir(source_path.expanduser().resolve()),
                        metadata=metadata,
                    ),
                    allow_source_workspace_writes,
                )
            )
        except SystemExit as exc:
            # A long-lived service must not die because one registered
            # workspace is missing or mid-sync; skip it and keep serving.
            sys.stderr.write(f"skipping registry workspace {workspace_id!r}: {exc}\n")
    return out


def discover_explorer_workspace_configs(
    roots: tuple[Path, ...],
    allow_source_workspace_writes: bool,
) -> list[ExplorerWorkspaceConfig]:
    """Discover tssearch workspaces under configured root directories."""

    out: list[ExplorerWorkspaceConfig] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for manifest in sorted(root.rglob("manifest.json")):
            source = manifest.parent
            if not source.name.startswith("tssearch_"):
                continue
            if not (source / "tree.json").exists():
                continue
            workspace_id = slugify_workspace_id(source.name)
            project_dir = infer_project_dir(source)
            state_dir = (
                project_dir / "local_explorer_state"
                if project_dir is not None
                else default_state_dir_for_source(source, workspace_id)
            )
            out.append(
                validate_explorer_workspace_config(
                    ExplorerWorkspaceConfig(
                        workspace_id=workspace_id,
                        display_name=source.name,
                        source_directory=source,
                        explorer_state_directory=state_dir,
                        project_directory=project_dir,
                        metadata={"discovered_from": str(root)},
                    ),
                    allow_source_workspace_writes,
                )
            )
    return out


def deduplicate_explorer_workspace_configs(
    workspaces: list[ExplorerWorkspaceConfig],
) -> list[ExplorerWorkspaceConfig]:
    """Return workspaces with duplicate workspace ids removed."""

    seen: set[str] = set()
    out: list[ExplorerWorkspaceConfig] = []
    for workspace in workspaces:
        if workspace.workspace_id in seen:
            continue
        seen.add(workspace.workspace_id)
        out.append(workspace)
    return out


def infer_project_dir(source: Path) -> Path | None:
    """Infer the parent project directory for a local_mirror workspace."""

    parts = source.parts
    marker = ("local_mirror",)
    for index, part in enumerate(parts):
        if part == marker[0] and index > 0:
            return Path(*parts[:index])
    return None


def service_state_directory(config: ExplorerServerConfig) -> Path:
    """Return the service-level state directory (not tied to any workspace)."""

    if config.workspace_registry_path is not None:
        return config.workspace_registry_path.parent / "service_state"
    return Path("/tmp") / "ts_explorer_state" / "_service"


def serve_forever(config: ExplorerServerConfig, *, open_url_file: Path | None = None) -> int:
    """Start the threaded HTTP server and block until interrupted."""

    directory = ExplorerWorkspaceDirectory(config)
    workspaces = directory.current_workspaces()
    state_dir = service_state_directory(config)
    state_dir.mkdir(parents=True, exist_ok=True)
    write_state_file(
        state_dir,
        "server.json",
        {
            "default_workspace": directory.default_workspace_id(),
            "workspaces": [summarize_explorer_workspace_config(workspace) for workspace in workspaces],
            "host": config.bind_host,
            "port": config.bind_port,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "read_only_source": not config.allow_source_workspace_writes,
            "registry_path": str(config.workspace_registry_path) if config.workspace_registry_path else "",
        },
    )
    handler_class = make_handler(config, directory)
    server = ThreadingHTTPServer((config.bind_host, config.bind_port), handler_class)
    url = f"http://{config.bind_host}:{server.server_address[1]}"
    if open_url_file is not None:
        open_url_file.parent.mkdir(parents=True, exist_ok=True)
        open_url_file.write_text(url + "\n", encoding="utf-8")
    print(f"{APP_NAME}: {url}", flush=True)
    print(f"workspaces: {len(workspaces)}", flush=True)
    if config.workspace_registry_path is not None:
        print(f"registry (hot-reloaded): {config.workspace_registry_path}", flush=True)
    default_id = directory.default_workspace_id()
    if default_id:
        print(f"default_workspace: {default_id}", flush=True)
    if _build_allowed_hosts(config) is None:
        print(
            f"WARNING: bound to wildcard host {config.bind_host!r}; Host header "
            "validation disabled — DNS rebinding protection requires a loopback bind.",
            file=sys.stderr, flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.server_close()
    return 0


_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "*"})


def _build_allowed_hosts(
    config: ExplorerServerConfig,
    *,
    effective_bind_port: int | None = None,
) -> frozenset[str] | None:
    """Return the set of acceptable Host header values, or None to skip the check.

    Returning None signals an opt-in to "trust any Host" semantics. We only do
    that when the user explicitly bound to a wildcard address — in that case
    they want LAN/external clients to reach the server by whatever hostname
    they have, and we can't enumerate those names ahead of time.

    For loopback binds (the default), we enforce a strict allowlist so DNS
    rebinding attacks can't trick a victim's browser into using our service
    as a confused deputy that exfiltrates workspace files.
    """
    if config.bind_host in _WILDCARD_HOSTS:
        return None
    port = config.bind_port if effective_bind_port is None else effective_bind_port
    allowed: set[str] = set()
    for host in ("127.0.0.1", "localhost", "[::1]", config.bind_host):
        allowed.add(f"{host}:{port}".lower())
        allowed.add(host.lower())
    return frozenset(allowed)


def make_handler(
    config: ExplorerServerConfig,
    directory: ExplorerWorkspaceDirectory,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to one explorer configuration."""

    class ExplorerHandler(BaseHTTPRequestHandler):
        """HTTP request handler for explorer UI and JSON API routes."""

        server_version = "TSHypothesisExplorer/0.1"

        def _host_ok(self) -> bool:
            """Return true when the Host header is allowed."""

            allowed_hosts = _build_allowed_hosts(
                config,
                effective_bind_port=int(self.server.server_address[1]),
            )
            if allowed_hosts is None:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            return host in allowed_hosts

        def do_GET(self) -> None:  # noqa: N802
            """Serve a GET request for the explorer UI or JSON API."""

            if not self._host_ok():
                host = (self.headers.get("Host") or "").strip()
                sys.stderr.write(
                    f"refused Host {host!r} from {self.client_address[0]}\n"
                )
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "bad_host",
                    "Host header not in allowlist; refusing for DNS-rebinding protection.",
                )
                return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if path == "/" or path == "/index.html":
                    self.send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
                    return
                if path == "/api/workspaces":
                    self.send_json(build_workspaces_api_payload(directory))
                    return
                if path.startswith("/api/workspace/"):
                    workspace_id, rest = parse_workspace_api_path(path)
                    workspace = directory.get_by_id(workspace_id)
                    self.route_workspace_api(workspace, rest, query)
                    return
                workspace = directory.get_default()
                if path == "/api/job":
                    self.send_json(load_explorer_workspace_api_payload(workspace.source_directory, workspace=workspace))
                    return
                if path == "/api/tree":
                    self.send_json(build_strict_v2_explorer_graph_payload(workspace.source_directory))
                    return
                if path == "/api/mechanism":
                    self.send_json(read_json_optional(workspace.source_directory / "mechanism_model.json"))
                    return
                if path == "/api/evidence":
                    self.send_json(read_json_optional(workspace.source_directory / "evidence_registry.json"))
                    return
                if path.startswith("/api/node/"):
                    node_id, rest = parse_node_path(path)
                    if rest == "":
                        self.send_json(load_node_payload(workspace.source_directory, node_id))
                        return
                    if rest.startswith("markdown/"):
                        name = rest.split("/", 1)[1]
                        self.send_json(load_node_markdown(workspace.source_directory, node_id, name))
                        return
                    if rest == "files":
                        self.send_json(list_node_files(workspace.source_directory, node_id))
                        return
                if path == "/api/file":
                    rel = first_query(query, "path")
                    self.send_json(read_workspace_file(workspace.source_directory, rel))
                    return
                self.send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"No route: {path}")
            except HTTPError as exc:
                self.send_error_json(exc.http_status, exc.code, exc.message)
            except Exception as exc:  # pragma: no cover - defensive HTTP boundary
                self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", str(exc))

        def route_workspace_api(
            self,
            workspace: ExplorerWorkspaceConfig,
            rest: str,
            query: dict[str, list[str]],
        ) -> None:
            """Route a workspace-scoped API request."""

            if rest in {"", "job"}:
                self.send_json(load_explorer_workspace_api_payload(workspace.source_directory, workspace=workspace))
                return
            if rest == "tree":
                self.send_json(build_strict_v2_explorer_graph_payload(workspace.source_directory))
                return
            if rest == "mechanism":
                self.send_json(read_json_optional(workspace.source_directory / "mechanism_model.json"))
                return
            if rest == "evidence":
                self.send_json(read_json_optional(workspace.source_directory / "evidence_registry.json"))
                return
            if rest == "file":
                rel = first_query(query, "path")
                self.send_json(read_workspace_file(workspace.source_directory, rel))
                return
            if rest.startswith("node/"):
                node_id, node_rest = parse_node_rest(rest)
                if node_rest == "":
                    self.send_json(load_node_payload(workspace.source_directory, node_id))
                    return
                if node_rest.startswith("markdown/"):
                    name = node_rest.split("/", 1)[1]
                    self.send_json(load_node_markdown(workspace.source_directory, node_id, name))
                    return
                if node_rest == "files":
                    self.send_json(list_node_files(workspace.source_directory, node_id))
                    return
            raise HTTPError(HTTPStatus.NOT_FOUND, "not_found", f"No workspace route: {rest}")

        def log_message(self, fmt: str, *args: Any) -> None:
            """Write HTTP access logs to stderr."""

            sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

        def send_json(self, payload: Any, http_status: HTTPStatus = HTTPStatus.OK) -> None:
            """Send a JSON response body."""

            raw = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            self.send_response(http_status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def send_text(
            self,
            text: str,
            *,
            http_status: HTTPStatus = HTTPStatus.OK,
            content_type: str = "text/plain; charset=utf-8",
        ) -> None:
            """Send a text response body."""

            raw = text.encode("utf-8")
            self.send_response(http_status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def send_error_json(self, http_status: HTTPStatus, code: str, message: str) -> None:
            """Send a structured JSON error response."""

            self.send_json({"error": {"code": code, "message": message}}, http_status=http_status)

    return ExplorerHandler


class HTTPError(Exception):
    """HTTP error carrying HTTP status, code, and user-visible message."""

    def __init__(self, http_status: HTTPStatus, code: str, message: str) -> None:
        """Create an HTTP error for conversion into a JSON response."""

        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message


def require_workspace(source: Path) -> None:
    """Require the source directory to contain core TS workspace files."""

    missing = [name for name in ("manifest.json", "tree.json") if not (source / name).exists()]
    if missing:
        raise SystemExit(f"source is not a tssearch workspace, missing: {', '.join(missing)}")


def build_workspaces_api_payload(directory: ExplorerWorkspaceDirectory) -> dict[str, Any]:
    """Return the live workspaces list payload for the explorer API."""

    return {
        "default_workspace": directory.default_workspace_id(),
        "workspaces": [summarize_explorer_workspace_config(workspace) for workspace in directory.current_workspaces()],
    }


def summarize_explorer_workspace_config(workspace: ExplorerWorkspaceConfig) -> dict[str, Any]:
    """Return a compact JSON summary for one configured workspace."""

    manifest = read_json_optional(workspace.source_directory / "manifest.json")
    pathway = summarize_pathway_model(read_json_optional(workspace.source_directory / "pathway_model.json"))
    metadata = workspace.metadata or {}
    accepted_ts = first_nonempty_string(manifest.get("current_accepted_ts"))
    claim_state = derive_workspace_claim_state(accepted_ts=accepted_ts, pathway_summary=pathway)
    active_pathway = pathway.get("active_pathway") if isinstance(pathway.get("active_pathway"), dict) else {}
    pathway_status = clean_string(active_pathway.get("status")) if active_pathway else ""
    return {
        "id": workspace.workspace_id,
        "name": workspace.display_name,
        "source": str(workspace.source_directory),
        "state_dir": str(workspace.explorer_state_directory),
        "project_dir": str(workspace.project_directory) if workspace.project_directory is not None else "",
        "system": first_nonempty_string(manifest.get("system"), manifest.get("system_slug"), manifest.get("root"), workspace.source_directory.name),
        "charge": manifest.get("charge", metadata.get("charge", "")),
        "multiplicity": manifest.get("multiplicity", metadata.get("multiplicity", "")),
        "claim_state": claim_state,
        "accepted_ts": accepted_ts,
        "pathway_status": pathway_status,
        "pathway": pathway,
        "metadata": metadata,
    }


def derive_workspace_claim_state(*, accepted_ts: str, pathway_summary: dict[str, Any]) -> str:
    """Return the workspace-level state without conflating one TS with a full pathway."""

    if bool(pathway_summary.get("present")) and clean_string(pathway_summary.get("mode")) == "multi_step":
        active = pathway_summary.get("active_pathway") if isinstance(pathway_summary.get("active_pathway"), dict) else {}
        status = clean_string(active.get("status")) if active else ""
        if status in {"complete", "partial", "ambiguous", "rejected", "hypothesis"}:
            return f"pathway_{status}"
        return "pathway_hypothesis"
    return "accepted_ts" if accepted_ts else "searching"


def load_explorer_workspace_api_payload(
    source: Path,
    *,
    workspace: ExplorerWorkspaceConfig | None = None,
) -> dict[str, Any]:
    """Load all JSON needed for the explorer main workspace view."""

    manifest = read_json_optional(source / "manifest.json")
    mechanism = read_json_optional(source / "mechanism_model.json")
    graph = build_strict_v2_explorer_graph_payload(source)
    return {
        "app": APP_NAME,
        "source": str(source),
        "manifest": manifest,
        "mechanism": mechanism,
        "evidence_summary": graph.get("evidence_summary") or {"count": 0, "by_kind": {}, "by_state": {}},
        "graph": graph,
        "workspace": summarize_explorer_workspace_config(workspace) if workspace is not None else {},
        "read_only": True,
    }


def build_strict_v2_explorer_graph_payload(source: Path) -> dict[str, Any]:
    """Build the strict v2 graph payload used by web and inspect routes."""

    if normalize_ts_workspace_to_explorer_graph is None:
        raise RuntimeError("strict v2 normalizer could not be imported")
    payload = normalize_ts_workspace_to_explorer_graph(source)
    if payload.get("schema") != "ts-explorer-graph-v2":
        raise RuntimeError(f"normalizer returned unsupported schema: {payload.get('schema')}")
    if validate_ts_workspace_contract is not None:
        payload["validation"] = validate_ts_workspace_contract(source)
    return payload


def load_node_payload(source: Path, node_id: str) -> dict[str, Any]:
    """Load normalized and raw details for one node."""

    assert_safe_node_id(node_id)
    node_dir = source / "nodes" / node_id
    node_json = read_json_optional(node_dir / "node.json")
    if not node_dir.exists():
        raise HTTPError(HTTPStatus.NOT_FOUND, "node_not_found", f"Node not found: {node_id}")
    graph = build_strict_v2_explorer_graph_payload(source)
    normalized_node = next(
        (
            item
            for item in list_or_empty(graph.get("nodes"))
            if isinstance(item, dict) and clean_string(item.get("id")) == node_id
        ),
        {},
    )
    if not normalized_node:
        raise HTTPError(HTTPStatus.NOT_FOUND, "node_not_found", f"Node not found in normalized graph: {node_id}")
    node_for_ui = {**node_json, **normalized_node}
    normalized_evidence = graph.get("evidence") if isinstance(graph.get("evidence"), dict) else {}
    records = [
        item
        for item in list_or_empty(normalized_evidence.get("records"))
        if isinstance(item, dict) and clean_string(item.get("node_id")) == node_id
    ]
    markdown = {
        name: read_text_optional(node_dir / filename)
        for name, filename in {
            "hypothesis": "hypothesis.md",
            "decision_card": "decision_card.md",
            "reflection": "reflection.md",
            "report": "report.md",
        }.items()
    }
    files = list_node_files(source, node_id)
    return {
        "node_id": node_id,
        "node": node_for_ui,
        "markdown": markdown,
        "evidence": records,
        "files": files,
        "file_notes": infer_gaussian_file_notes(source, node_id, files.get("files", [])),
    }


def load_node_markdown(source: Path, node_id: str, name: str) -> dict[str, Any]:
    """Load one node markdown artifact by logical name."""

    assert_safe_node_id(node_id)
    allowed = {
        "hypothesis": "hypothesis.md",
        "decision_card": "decision_card.md",
        "reflection": "reflection.md",
        "report": "report.md",
    }
    if name not in allowed:
        raise HTTPError(HTTPStatus.BAD_REQUEST, "unsupported_markdown", f"Unsupported markdown: {name}")
    path = source / "nodes" / node_id / allowed[name]
    return {"node_id": node_id, "name": name, "text": read_text_optional(path), "path": rel_path(source, path)}


def list_node_files(source: Path, node_id: str) -> dict[str, Any]:
    """List readable files under one node directory."""

    assert_safe_node_id(node_id)
    node_dir = source / "nodes" / node_id
    if not node_dir.exists():
        tree = read_json_optional(source / "tree.json")
        tree_nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
        if node_id not in tree_nodes:
            raise HTTPError(HTTPStatus.NOT_FOUND, "node_not_found", f"Node not found: {node_id}")
        return {"node_id": node_id, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(node_dir.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "path": rel_path(source, path),
                "name": path.name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
                "mime": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
            }
        )
    return {"node_id": node_id, "files": files}


def infer_gaussian_file_notes(source: Path, node_id: str, files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return notes that explain Gaussian checkpoint references not present locally."""

    node_dir = source / "nodes" / node_id
    if not node_dir.exists():
        return []
    existing_names = {clean_string(item.get("name")) for item in files if isinstance(item, dict)}
    notes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for input_path in sorted((node_dir / "inputs").glob("*.gjf")) + sorted((node_dir / "inputs").glob("*.com")):
        if not input_path.is_file() or input_path.stat().st_size > MAX_TEXT_BYTES:
            continue
        for raw_line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = raw_line.strip()
            lower = stripped.lower()
            if not (lower.startswith("%chk=") or lower.startswith("%oldchk=")):
                continue
            key, value = stripped.split("=", 1)
            chk_name = clean_string(Path(value.strip()).name)
            if not chk_name or chk_name in existing_names:
                continue
            note_key = (key.lower(), chk_name)
            if note_key in seen:
                continue
            seen.add(note_key)
            notes.append(
                {
                    "kind": "gaussian_checkpoint",
                    "source": rel_path(source, input_path),
                    "checkpoint": chk_name,
                    "message": (
                        f"{key} references {chk_name}. Gaussian writes relative checkpoint files in the remote run "
                        "directory; local explorer mirrors usually omit .chk files unless explicitly synced."
                    ),
                }
            )
    return notes


def read_workspace_file(source: Path, rel: str) -> dict[str, Any]:
    """Read a bounded text preview for a workspace-relative file."""

    if not rel:
        raise HTTPError(HTTPStatus.BAD_REQUEST, "missing_path", "Missing path.")
    path = safe_join(source, rel)
    if not path.exists() or not path.is_file():
        raise HTTPError(HTTPStatus.NOT_FOUND, "file_not_found", f"File not found: {rel}")
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise HTTPError(HTTPStatus.BAD_REQUEST, "file_too_large", f"File is larger than {MAX_TEXT_BYTES} bytes.")
    return {
        "path": rel_path(source, path),
        "text": path.read_text(encoding="utf-8", errors="replace"),
        "size": path.stat().st_size,
    }


def read_json_optional(path: Path) -> dict[str, Any]:
    """Read a JSON object when present, otherwise return an empty object."""

    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {"_read_error": str(exc), "_path": str(path)}
    return payload if isinstance(payload, dict) else {"_read_error": "JSON root is not an object", "_path": str(path)}


def read_json_required(path: Path) -> Any:
    """Read required JSON and abort CLI startup on parse failure."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise SystemExit(f"failed to read JSON {path}: {exc}") from exc


def read_text_optional(path: Path) -> str:
    """Read optional UTF-8 text, replacing invalid bytes."""

    if not path.exists() or not path.is_file():
        return ""
    if path.stat().st_size > MAX_TEXT_BYTES:
        return f"[file too large to preview: {path.stat().st_size} bytes]"
    return path.read_text(encoding="utf-8", errors="replace")


def write_state_file(state_directory: Path, name: str, payload: dict[str, Any]) -> None:
    """Write explorer-only runtime state into the service state directory."""

    path = state_directory / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_node_path(path: str) -> tuple[str, str]:
    """Parse legacy node API paths into node id and subresource."""

    prefix = "/api/node/"
    rest = path[len(prefix) :]
    parts = rest.split("/", 1)
    node_id = urllib.parse.unquote(parts[0])
    assert_safe_node_id(node_id)
    return node_id, parts[1] if len(parts) > 1 else ""


def parse_workspace_api_path(path: str) -> tuple[str, str]:
    """Parse workspace-scoped API paths into workspace id and endpoint."""

    prefix = "/api/workspace/"
    rest = path[len(prefix) :]
    parts = rest.split("/", 1)
    workspace_id = urllib.parse.unquote(parts[0])
    assert_safe_workspace_id(workspace_id)
    return workspace_id, parts[1] if len(parts) > 1 else ""


def parse_node_rest(rest: str) -> tuple[str, str]:
    """Parse node API suffixes into node id and logical endpoint."""

    prefix = "node/"
    node_rest = rest[len(prefix) :]
    parts = node_rest.split("/", 1)
    node_id = urllib.parse.unquote(parts[0])
    assert_safe_node_id(node_id)
    return node_id, parts[1] if len(parts) > 1 else ""


def assert_safe_workspace_id(workspace_id: str) -> None:
    """Reject workspace ids that are unsafe for routes or paths."""

    if (
        not workspace_id
        or "/" in workspace_id
        or "\\" in workspace_id
        or workspace_id in {".", ".."}
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in workspace_id)
    ):
        raise HTTPError(HTTPStatus.BAD_REQUEST, "bad_workspace_id", f"Unsafe workspace id: {workspace_id!r}")


def assert_safe_node_id(node_id: str) -> None:
    """Reject node ids that are unsafe for routes or paths."""

    if not node_id or "/" in node_id or "\\" in node_id or node_id in {".", ".."}:
        raise HTTPError(HTTPStatus.BAD_REQUEST, "bad_node_id", f"Unsafe node id: {node_id!r}")


def safe_join(root: Path, rel: str) -> Path:
    """Join a relative path while preventing traversal outside root."""

    normalized = posixpath.normpath(urllib.parse.unquote(rel).replace("\\", "/"))
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise HTTPError(HTTPStatus.BAD_REQUEST, "bad_path", f"Unsafe path: {rel!r}")
    path = (root / normalized).resolve()
    if not is_path_relative_to(path, root):
        raise HTTPError(HTTPStatus.BAD_REQUEST, "bad_path", f"Path escapes source: {rel!r}")
    return path


def rel_path(root: Path, path: Path) -> str:
    """Return path relative to root after resolving both paths."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def first_query(query: dict[str, list[str]], key: str) -> str:
    """Return the first query parameter value for key."""

    values = query.get(key) or []
    return values[0] if values else ""


INDEX_HTML = read_explorer_index_html()


if __name__ == "__main__":
    raise SystemExit(main())
