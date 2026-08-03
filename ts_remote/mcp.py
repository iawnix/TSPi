"""MCP 2.0 client for the manifest-bound TS cluster service."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from cluster_mcp.ts_jobs import validate_ts_submission_request

from .base import RemoteReceipt


class MCPClientError(RuntimeError):
    """Raised when the MCP transport or TS cluster contract is invalid."""


class ToolCaller(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MCPConnectionSettings:
    endpoint: str
    token: str | None = None
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "MCPConnectionSettings":
        endpoint = os.environ.get("TS_CLUSTER_MCP_URL", "").strip()
        if not endpoint:
            raise MCPClientError("TS_CLUSTER_MCP_URL is not configured")
        token = os.environ.get("TS_CLUSTER_MCP_TOKEN")
        timeout_raw = os.environ.get("TS_CLUSTER_MCP_TIMEOUT", "60")
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise MCPClientError("TS_CLUSTER_MCP_TIMEOUT must be numeric") from exc
        return cls(endpoint=endpoint, token=token, timeout_seconds=timeout).validated()

    def validated(self) -> "MCPConnectionSettings":
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise MCPClientError("TS cluster MCP endpoint must be an absolute HTTP(S) URL without credentials")
        if parsed.scheme == "http" and not _loopback_host(parsed.hostname):
            raise MCPClientError("Non-loopback TS cluster MCP endpoints require HTTPS")
        if self.token is not None:
            try:
                self.token.encode("ascii")
            except UnicodeEncodeError as exc:
                raise MCPClientError("TS cluster MCP token must contain only ASCII characters") from exc
            if len(self.token) < 32 or any(
                character.isspace() or character == "\x00" for character in self.token
            ):
                raise MCPClientError(
                    "TS cluster MCP token must be at least 32 non-whitespace ASCII characters"
                )
        if not 1 <= self.timeout_seconds <= 600:
            raise MCPClientError("TS cluster MCP timeout must be between 1 and 600 seconds")
        return self


class SDKToolCaller:
    """Open a short-lived MCP 2.0 client for one host-side tool invocation."""

    def __init__(self, settings: MCPConnectionSettings, *, server: object | None = None) -> None:
        self.settings = settings.validated()
        self.server = server

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not name or not isinstance(arguments, dict):
            raise MCPClientError("MCP tool call requires a name and object arguments")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call_tool(name, arguments))
        raise MCPClientError("Synchronous TS MCP calls cannot run inside an active event loop")

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            from mcp import Client
        except ImportError as exc:
            raise MCPClientError(
                "MCP Python SDK 2.0 is not installed in the TSAgentSkill runtime"
            ) from exc

        if self.server is not None:
            async with Client(
                self.server,
                read_timeout_seconds=self.settings.timeout_seconds,
                raise_exceptions=True,
            ) as client:
                result = await client.call_tool(name, arguments)
                return _structured_result(result)

        target: object = self.settings.endpoint
        if self.settings.token is not None:
            try:
                import httpx2
                from mcp.client.streamable_http import streamable_http_client
            except ImportError as exc:
                raise MCPClientError("Authenticated MCP transport dependencies are unavailable") from exc
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {self.settings.token}"}
            ) as http_client:
                target = streamable_http_client(self.settings.endpoint, http_client=http_client)
                async with Client(
                    target,
                    read_timeout_seconds=self.settings.timeout_seconds,
                    raise_exceptions=True,
                ) as client:
                    result = await client.call_tool(name, arguments)
                    return _structured_result(result)
        async with Client(
            target,
            read_timeout_seconds=self.settings.timeout_seconds,
            raise_exceptions=True,
        ) as client:
            result = await client.call_tool(name, arguments)
            return _structured_result(result)


class TSClusterMCPClient:
    def __init__(self, caller: ToolCaller) -> None:
        self.caller = caller

    def capabilities(self) -> dict[str, Any]:
        return self.caller.call_tool("cluster_capabilities", {})

    def ensure_directory(self, path: str) -> None:
        result = self.caller.call_tool("ts_ensure_directory", {"path": path})
        if result.get("path") != path or not isinstance(result.get("created"), bool):
            raise MCPClientError(f"MCP server did not ensure the requested directory: {path}")

    def upload_file(self, source: Path, remote_path: str, *, chunk_bytes: int | None = None) -> dict[str, Any]:
        source = source.expanduser().resolve(strict=True)
        if not source.is_file() or source.is_symlink():
            raise MCPClientError(f"Upload source must be a regular non-symlink file: {source}")
        size = source.stat().st_size
        digest = _sha256(source)
        started = self.caller.call_tool(
            "ts_prepare_upload",
            {"path": remote_path, "size": size, "sha256": digest},
        )
        if started.get("replayed") is True:
            if (
                started.get("path") != remote_path
                or started.get("size") != size
                or not secrets.compare_digest(str(started.get("sha256", "")), digest)
            ):
                raise MCPClientError("MCP upload replay does not match the local source")
            return started
        upload_id = started.get("upload_id")
        if not isinstance(upload_id, str) or not upload_id:
            raise MCPClientError("MCP server returned no upload_id")
        server_limit = started.get("max_chunk_bytes")
        selected_chunk = chunk_bytes or (server_limit if isinstance(server_limit, int) else 1024 * 1024)
        if not isinstance(server_limit, int) or not 1 <= selected_chunk <= server_limit:
            raise MCPClientError("Requested upload chunk size exceeds the MCP server limit")
        offset = 0
        try:
            with source.open("rb") as handle:
                while payload := handle.read(selected_chunk):
                    response = self.caller.call_tool(
                        "upload_chunk",
                        {
                            "upload_id": upload_id,
                            "offset": offset,
                            "data_base64": base64.b64encode(payload).decode("ascii"),
                        },
                    )
                    offset += len(payload)
                    if response.get("received") != offset:
                        raise MCPClientError("MCP upload offset acknowledgement is inconsistent")
            finished = self.caller.call_tool("finish_upload", {"upload_id": upload_id})
        except Exception:
            try:
                self.caller.call_tool("abort_upload", {"upload_id": upload_id})
            except Exception:
                pass
            raise
        if (
            finished.get("path") != remote_path
            or finished.get("size") != size
            or not secrets.compare_digest(str(finished.get("sha256", "")), digest)
        ):
            raise MCPClientError("MCP upload result does not match the local source")
        return {**finished, "replayed": False}

    def submit(self, request: dict[str, Any]) -> RemoteReceipt:
        try:
            normalized = validate_ts_submission_request(request)
        except Exception as exc:
            raise MCPClientError(f"Invalid TS cluster job request: {exc}") from exc
        result = self.caller.call_tool("ts_submit_job", {"request": normalized})
        if result.get("schema_version") != "ts-cluster-submission-result/1":
            raise MCPClientError("MCP server returned an invalid TS submission result")
        if result.get("state") != "submitted":
            raise MCPClientError("MCP server did not return a submitted TS job")
        for key in ("submission_id", "intent_id", "intent_digest", "node_id", "backend"):
            if result.get(key) != normalized.get(key):
                raise MCPClientError(f"MCP submission result does not match request field: {key}")
        if result.get("expected_artifacts") != normalized["expected_artifacts"]:
            raise MCPClientError("MCP submission result changed the expected artifact manifest")
        job_id = result.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise MCPClientError("MCP submission result has no scheduler job_id")
        return RemoteReceipt(
            node_id=str(normalized["node_id"]),
            host="cluster-mcp",
            remote_dir=str(normalized["workdir"]),
            command=["mcp", "ts_submit_job", str(normalized["submission_id"])],
            receipt_path=f"{str(normalized['workdir']).rstrip('/')}/ts_submission.json",
            scheduler_id=job_id,
            metadata={
                "schema_version": str(result["schema_version"]),
                "submission_id": str(result["submission_id"]),
                "intent_id": str(result["intent_id"]),
                "intent_digest": str(result["intent_digest"]),
                "backend": str(result["backend"]),
                "expected_artifacts": json.dumps(result.get("expected_artifacts", [])),
                "replayed": str(bool(result.get("replayed", False))).lower(),
            },
        )

    def status(self, submission_id: str, *, include_history: bool = False) -> dict[str, Any]:
        result = self.caller.call_tool(
            "ts_get_submission",
            {"submission_id": submission_id, "include_history": include_history},
        )
        if result.get("schema_version") != "ts-cluster-submission/1":
            raise MCPClientError("MCP server returned an invalid TS submission status")
        if result.get("submission_id") != submission_id:
            raise MCPClientError("MCP submission status does not match submission_id")
        return result

    def cancel(self, submission_id: str, job_id: str) -> dict[str, Any]:
        result = self.caller.call_tool(
            "ts_cancel_submission",
            {"submission_id": submission_id, "confirmation": f"{submission_id}:{job_id}"},
        )
        if (
            result.get("schema_version") != "ts-cluster-cancellation-result/1"
            or result.get("state") != "cancelled"
            or result.get("submission_id") != submission_id
            or result.get("job_id") != job_id
        ):
            raise MCPClientError("MCP cancellation result does not match the requested submission")
        return result

    def read_tail(self, remote_path: str, *, max_bytes: int = 32 * 1024) -> dict[str, Any]:
        if isinstance(max_bytes, bool) or not 1 <= max_bytes <= 1024 * 1024:
            raise MCPClientError("MCP tail max_bytes must be between 1 and 1048576")
        before = self.caller.call_tool(
            "file_info",
            {"path": remote_path, "include_sha256": True},
        )
        if before.get("path") != remote_path or before.get("type") != "file":
            raise MCPClientError("MCP tail source is not the requested regular file")
        size = before.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise MCPClientError("MCP tail source has an invalid size")
        digest = _validated_sha256(before.get("sha256"), "MCP tail source")
        offset = max(0, size - max_bytes)
        chunk = self.caller.call_tool(
            "download_chunk",
            {"path": remote_path, "offset": offset, "max_bytes": max_bytes},
        )
        if (
            chunk.get("path") != remote_path
            or chunk.get("offset") != offset
            or chunk.get("size") != size
            or chunk.get("eof") is not True
        ):
            raise MCPClientError("MCP tail chunk metadata is inconsistent")
        try:
            payload = base64.b64decode(str(chunk.get("data_base64", "")), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MCPClientError("MCP tail returned invalid base64") from exc
        if (
            len(payload) > max_bytes
            or chunk.get("next_offset") != offset + len(payload)
            or offset + len(payload) != size
        ):
            raise MCPClientError("MCP tail next_offset is inconsistent")
        after = self.caller.call_tool(
            "file_info",
            {"path": remote_path, "include_sha256": True},
        )
        if (
            after.get("path") != remote_path
            or after.get("type") != "file"
            or after.get("size") != size
            or not secrets.compare_digest(_validated_sha256(after.get("sha256"), "MCP tail source"), digest)
        ):
            raise MCPClientError("MCP tail source changed during transfer")
        return {
            "path": remote_path,
            "offset": offset,
            "size": size,
            "sha256": digest,
            "data": payload,
        }

    def download_file(
        self,
        remote_path: str,
        destination: Path,
        *,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        destination = destination.expanduser().resolve()
        if destination.exists() or destination.is_symlink():
            raise MCPClientError(f"Download destination already exists: {destination}")
        descriptor = self.caller.call_tool(
            "file_info",
            {"path": remote_path, "include_sha256": True},
        )
        if descriptor.get("path") != remote_path or descriptor.get("type") != "file":
            raise MCPClientError("MCP download source is not the requested regular file")
        remote_size = descriptor.get("size")
        if isinstance(remote_size, bool) or not isinstance(remote_size, int) or remote_size < 0:
            raise MCPClientError("MCP download source has an invalid size")
        remote_digest = _validated_sha256(descriptor.get("sha256"), "MCP download source")
        if expected_sha256 is not None:
            expected_digest = _validated_sha256(expected_sha256, "Expected download")
            if not secrets.compare_digest(remote_digest, expected_digest):
                raise MCPClientError("MCP download source SHA-256 does not match the expected artifact")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        offset = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("wb") as handle:
                while True:
                    chunk = self.caller.call_tool(
                        "download_chunk",
                        {"path": remote_path, "offset": offset},
                    )
                    if chunk.get("path") != remote_path or chunk.get("offset") != offset:
                        raise MCPClientError("MCP download chunk metadata is inconsistent")
                    if chunk.get("size") != remote_size:
                        raise MCPClientError("MCP download source size changed during transfer")
                    try:
                        payload = base64.b64decode(str(chunk.get("data_base64", "")), validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise MCPClientError("MCP download returned invalid base64") from exc
                    handle.write(payload)
                    digest.update(payload)
                    offset += len(payload)
                    if chunk.get("next_offset") != offset:
                        raise MCPClientError("MCP download next_offset is inconsistent")
                    if chunk.get("eof") is True:
                        if remote_size != offset:
                            raise MCPClientError("MCP download final size is inconsistent")
                        break
            actual = digest.hexdigest()
            if not secrets.compare_digest(actual, remote_digest):
                raise MCPClientError("MCP download content changed during transfer")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return {"path": str(destination), "size": offset, "sha256": actual}


def build_ts_job_request(
    *,
    submission_id: str,
    intent_id: str,
    intent_digest: str,
    node_id: str,
    backend: str,
    workdir: str,
    script_path: str,
    input_files: dict[str, Path],
    expected_artifacts: list[str],
    execution: dict[str, Any],
) -> dict[str, Any]:
    manifest = []
    for remote_path, local_path in sorted(input_files.items()):
        source = local_path.expanduser().resolve(strict=True)
        if not source.is_file() or source.is_symlink():
            raise MCPClientError(f"TS job input must be a regular non-symlink file: {source}")
        manifest.append(
            {
                "path": remote_path,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            }
        )
    request = {
        "schema_version": "ts-cluster-job/1",
        "submission_id": submission_id,
        "intent_id": intent_id,
        "intent_digest": intent_digest,
        "node_id": node_id,
        "backend": backend,
        "script_path": script_path,
        "workdir": workdir,
        "input_manifest": manifest,
        "expected_artifacts": expected_artifacts,
        "execution": execution,
    }
    try:
        return validate_ts_submission_request(request)
    except Exception as exc:
        raise MCPClientError(f"Invalid TS cluster job request: {exc}") from exc


def _structured_result(result: Any) -> dict[str, Any]:
    if getattr(result, "is_error", False):
        raise MCPClientError("MCP tool returned an error result")
    value = getattr(result, "structured_content", None)
    if isinstance(value, dict) and set(value) == {"result"} and isinstance(value["result"], dict):
        value = value["result"]
    if not isinstance(value, dict):
        raise MCPClientError("MCP tool returned no structured object result")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MCPClientError(f"{label} SHA-256 is invalid")
    return value


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
