"""MCP tool definitions. Core behavior remains testable without the SDK."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.types.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

from . import __version__
from .config import AppConfig
from .errors import ConfigurationError
from .http_transport import (
    EnvironmentBearerTokenVerifier,
    load_http_token,
    mcp_auth_settings,
    validate_http_settings,
)
from .service import ClusterService

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
IDEMPOTENT_MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)
IDEMPOTENT_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)


def create_server(
    config: AppConfig,
    *,
    principal: str | None = None,
    auth_method: str = "none",
    transport: str = "stdio",
) -> MCPServer:
    if transport not in {"stdio", "streamable-http"}:
        raise ConfigurationError("Unsupported MCP transport")
    if transport == "streamable-http":
        if not config.auth.required or principal is None:
            raise ConfigurationError("Streamable HTTP requires configured principal authentication")
        if auth_method != "http-bearer":
            raise ConfigurationError("Streamable HTTP requires http-bearer authentication")
        validate_http_settings(config.http)

    service = ClusterService(config, principal=principal, auth_method=auth_method)
    service.initialize()
    instructions = (
        "Operate OpenPBS through structured tools and use workspace-relative paths. "
        "Inspect queues before submission and never run heavy computations on the login node. "
        "GPU IDs are manually coordinated physical devices, not scheduler isolation. "
        "TS workflow clients must use ts_submit_job, ts_get_submission, and "
        "ts_cancel_submission so intent and idempotency bindings are preserved."
    )
    if transport == "streamable-http":
        verifier = EnvironmentBearerTokenVerifier(
            token=load_http_token(config.http),
            principal=service.session_principal.name,
            scopes=service.session_principal.scopes,
        )
        mcp = MCPServer(
            "cluster-mcp",
            version=__version__,
            instructions=instructions,
            token_verifier=verifier,
            auth=mcp_auth_settings(config.http),
        )
    else:
        mcp = MCPServer("cluster-mcp", version=__version__, instructions=instructions)

    @mcp.tool(annotations=READ_ONLY)
    def cluster_capabilities() -> dict[str, Any]:
        """Return configured features, limits, queues, workspace, and security notes."""
        capabilities = service.capabilities()
        capabilities["mcp_protocol"] = {
            "latest": LATEST_PROTOCOL_VERSION,
            "supported": list(SUPPORTED_PROTOCOL_VERSIONS),
            "dual_era": True,
        }
        return capabilities

    @mcp.tool(annotations=READ_ONLY)
    def ts_control_health() -> dict[str, Any]:
        """Check the TS submission registry, workspace storage, and Gaussian profile."""
        return service.control_health()

    @mcp.tool(annotations=READ_ONLY)
    def list_queues() -> dict[str, Any]:
        """List OpenPBS queues and mark which queues this server permits for submission."""
        return service.list_queues()

    @mcp.tool(annotations=READ_ONLY)
    def list_nodes() -> dict[str, Any]:
        """List compact OpenPBS node availability including free/total CPUs and GPUs."""
        return service.list_nodes()

    @mcp.tool(annotations=READ_ONLY)
    def list_jobs(owner: str | None = None) -> dict[str, Any]:
        """List jobs for the server user; other owners require explicit configuration permission."""
        return service.list_jobs(owner)

    @mcp.tool(annotations=READ_ONLY)
    def get_job(job_id: str, include_history: bool = False) -> dict[str, Any]:
        """Get normalized details for one active or historical OpenPBS job."""
        return service.get_job(job_id, include_history=include_history)

    @mcp.tool(annotations=MUTATING)
    def hold_job(job_id: str) -> dict[str, Any]:
        """Place one job owned by the server user on hold."""
        return service.control_job("hold", job_id)

    @mcp.tool(annotations=MUTATING)
    def release_job(job_id: str) -> dict[str, Any]:
        """Release one held job owned by the server user."""
        return service.control_job("release", job_id)

    @mcp.tool(annotations=MUTATING)
    def alter_job_walltime(job_id: str, walltime: str) -> dict[str, Any]:
        """Change an owned active job's walltime using validated HH:MM:SS syntax."""
        return service.alter_job_walltime(job_id, walltime)

    @mcp.tool(annotations=DESTRUCTIVE)
    def delete_job(job_id: str, confirmation: str) -> dict[str, Any]:
        """Delete one owned job; confirmation must exactly equal job_id."""
        return service.control_job("delete", job_id, confirmation=confirmation)

    @mcp.tool(annotations=MUTATING)
    def submit_script(
        script_path: str,
        name: str,
        queue: str,
        workdir: str = ".",
        nodes: int = 1,
        ncpus: int = 1,
        memory: str = "4gb",
        walltime: str = "01:00:00",
        ngpus: int = 0,
        mpiprocs: int | None = None,
        ompthreads: int | None = None,
        host: str | None = None,
        place: str | None = None,
        environment: dict[str, str] | None = None,
        gpu_devices: list[int] | None = None,
    ) -> dict[str, Any]:
        """Submit an uploaded Bash script through a server-generated, validated PBS wrapper."""
        return service.submit_script(
            script_path=script_path,
            name=name,
            queue=queue,
            workdir=workdir,
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
            environment=environment,
            gpu_devices=gpu_devices,
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_software() -> dict[str, Any]:
        """List configured software profiles and installed Python adapter extensions."""
        return service.software_catalog()

    @mcp.tool(annotations=MUTATING)
    def submit_software_job(
        software: str,
        name: str,
        workdir: str = ".",
        arguments: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        queue: str | None = None,
        nodes: int = 1,
        ncpus: int = 1,
        memory: str = "4gb",
        walltime: str = "01:00:00",
        ngpus: int = 0,
        mpiprocs: int | None = None,
        ompthreads: int | None = None,
        host: str | None = None,
        place: str | None = None,
        environment: dict[str, str] | None = None,
        gpu_devices: list[int] | None = None,
    ) -> dict[str, Any]:
        """Submit a configured software profile or Python adapter as a validated PBS job."""
        return service.submit_software(
            software=software,
            name=name,
            workdir=workdir,
            arguments=arguments,
            parameters=parameters,
            queue=queue,
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
            environment=environment,
            gpu_devices=gpu_devices,
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_files(path: str = ".") -> dict[str, Any]:
        """List one workspace directory without following or exposing internal paths."""
        return service.list_files(path)

    @mcp.tool(annotations=READ_ONLY)
    def file_info(path: str, include_sha256: bool = False) -> dict[str, Any]:
        """Return metadata, and optionally SHA-256, for one workspace path."""
        return service.file_info(path, include_sha256=include_sha256)

    @mcp.tool(annotations=MUTATING)
    def create_directory(path: str, parents: bool = False) -> dict[str, Any]:
        """Create a private directory inside the workspace."""
        return service.create_directory(path, parents=parents)

    @mcp.tool(annotations=MUTATING)
    def start_upload(
        path: str,
        size: int,
        sha256: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Start a bounded upload; replacing a file requires files:overwrite."""
        return service.start_upload(path, size=size, sha256=sha256, overwrite=overwrite)

    @mcp.tool(annotations=MUTATING)
    def upload_chunk(upload_id: str, offset: int, data_base64: str) -> dict[str, Any]:
        """Append one base64 chunk at the exact expected byte offset."""
        return service.upload_chunk(upload_id, offset=offset, data_base64=data_base64)

    @mcp.tool(annotations=DESTRUCTIVE)
    def finish_upload(upload_id: str) -> dict[str, Any]:
        """Verify size and optional SHA-256, then atomically publish an upload."""
        return service.finish_upload(upload_id)

    @mcp.tool(annotations=DESTRUCTIVE)
    def abort_upload(upload_id: str) -> dict[str, Any]:
        """Remove an unfinished upload and its metadata."""
        return service.abort_upload(upload_id)

    @mcp.tool(annotations=READ_ONLY)
    def download_chunk(path: str, offset: int = 0, max_bytes: int | None = None) -> dict[str, Any]:
        """Download one base64 chunk from a regular file inside the workspace."""
        return service.download_chunk(path, offset=offset, max_bytes=max_bytes)

    @mcp.tool(annotations=READ_ONLY)
    def read_job_log(
        job_id: str,
        stream: str = "output",
        offset: int = 0,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Read a chunk of an owned job's output/error log when it is inside the workspace."""
        return service.job_log_chunk(job_id, stream=stream, offset=offset, max_bytes=max_bytes)

    @mcp.tool(annotations=IDEMPOTENT_MUTATING)
    def ts_submit_job(request: dict[str, Any]) -> dict[str, Any]:
        """Submit one manifest-bound TS calculation exactly once per submission_id."""
        return service.submit_ts_job(request)

    @mcp.tool(annotations=IDEMPOTENT_MUTATING)
    def ts_ensure_directory(path: str) -> dict[str, Any]:
        """Idempotently create one principal-workspace directory tree."""
        return service.ensure_ts_directory(path)

    @mcp.tool(annotations=IDEMPOTENT_MUTATING)
    def ts_prepare_upload(path: str, size: int, sha256: str) -> dict[str, Any]:
        """Start an upload or replay success when the exact remote file already exists."""
        return service.prepare_ts_upload(path, size=size, sha256=sha256)

    @mcp.tool(annotations=READ_ONLY)
    def ts_get_submission(
        submission_id: str,
        include_history: bool = False,
    ) -> dict[str, Any]:
        """Read one principal-owned TS submission and its normalized scheduler state."""
        return service.get_ts_submission(submission_id, include_history=include_history)

    @mcp.tool(annotations=IDEMPOTENT_DESTRUCTIVE)
    def ts_cancel_submission(submission_id: str, confirmation: str) -> dict[str, Any]:
        """Cancel one TS submission using exact submission_id:job_id confirmation."""
        return service.cancel_ts_submission(submission_id, confirmation=confirmation)

    return mcp
