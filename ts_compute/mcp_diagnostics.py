"""Read-only diagnostics for the host-side TS Cluster MCP connection."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from ts_remote.mcp import MCPClientError, MCPConnectionSettings, SDKToolCaller, TSClusterMCPClient


MCP_DIAGNOSTIC_MODES = frozenset({"status", "doctor", "queues"})
SCHEMA_VERSION = "ts-mcp-diagnostic/1"


def diagnose_mcp(mode: str = "status") -> dict[str, Any]:
    """Validate and probe one MCP connection without scheduler side effects."""

    if mode not in MCP_DIAGNOSTIC_MODES:
        raise ValueError(f"unsupported MCP diagnostic mode: {mode}")
    try:
        settings = _connection_settings()
    except Exception as exc:
        return _failure(mode, "configuration", exc)

    connection = {
        "endpoint": settings.endpoint,
        "authenticated": settings.token is not None,
        "timeout_seconds": settings.timeout_seconds,
    }
    try:
        client = _client(settings)
        if mode == "queues":
            result = {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "ok": True,
                "connection": connection,
                "queues": client.list_queues()["queues"],
            }
        else:
            result = {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "ok": True,
                "connection": connection,
                "capabilities": _capability_summary(client.capabilities()),
            }
            if mode == "doctor":
                result["checks"] = {
                    "configuration": "pass",
                    "connection": "pass",
                    "authentication": "pass",
                    "protocol": "pass",
                }
    except Exception as exc:
        return _failure(mode, "probe", exc, connection=connection)
    return _sanitize(result)


def _connection_settings() -> MCPConnectionSettings:
    return MCPConnectionSettings.from_environment()


def _client(settings: MCPConnectionSettings) -> TSClusterMCPClient:
    return TSClusterMCPClient(SDKToolCaller(settings))


def _failure(
    mode: str,
    phase: str,
    error: Exception,
    *,
    connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_class = _classify_error(error, phase)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "ok": False,
        "error": {
            "class": error_class,
            "phase": phase,
            "message": _redact_text(str(error) or type(error).__name__),
        },
    }
    if connection is not None:
        result["connection"] = connection
    if mode == "doctor":
        result["checks"] = _doctor_checks(error_class, phase)
    return _sanitize(result)


def _classify_error(error: Exception, phase: str) -> str:
    message = str(error).lower()
    if phase == "configuration":
        if "not configured" in message:
            return "configuration_missing"
        if "timeout" in message:
            return "timeout_configuration"
        if "token" in message or "ascii" in message or "whitespace" in message:
            return "authentication_configuration"
        if "endpoint" in message or "http" in message or "https" in message or "url" in message:
            return "endpoint_configuration"
        return "configuration_invalid"
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or "timeout" in message or "timed out" in message:
        return "timeout"
    if any(
        marker in message
        for marker in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "authentication failed",
            "invalid token",
            "bearer token",
        )
    ):
        return "authentication_failed"
    if "not authorized" in message or "scope" in message or "permission" in message:
        return "authorization_failed"
    if any(marker in message for marker in ("sdk", "dependency", "dependencies", "not installed", "import")):
        return "dependency_missing"
    if any(
        marker in message
        for marker in ("connection", "connect", "refused", "dns", "name resolution", "network", "unreachable")
    ):
        return "connection_failed"
    if isinstance(error, (MCPClientError, OSError)):
        return "protocol_error"
    return "unexpected_error"


def _doctor_checks(error_class: str, phase: str) -> dict[str, str]:
    checks = {
        "configuration": "pass" if phase != "configuration" else "fail",
        "connection": "not_run",
        "authentication": "not_run",
        "protocol": "not_run",
    }
    if phase == "probe":
        if error_class in {"connection_failed", "timeout"}:
            checks["connection"] = "fail"
        elif error_class in {"authentication_failed", "authorization_failed"}:
            checks["connection"] = "pass"
            checks["authentication"] = "fail"
        elif error_class == "dependency_missing":
            checks["configuration"] = "fail"
        else:
            checks["connection"] = "pass"
            checks["authentication"] = "pass"
            checks["protocol"] = "fail"
    return checks


def _capability_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MCPClientError("MCP server returned invalid cluster capabilities")
    summary = {
        key: payload[key]
        for key in (
            "server",
            "version",
            "transport",
            "actor",
            "scheduler",
            "workspace",
            "allowed_queues",
            "gpu_queues",
            "max_nodes",
            "job_submission_enabled",
            "job_control_enabled",
        )
        if key in payload
    }
    authentication = payload.get("authentication")
    if isinstance(authentication, dict):
        summary["authentication"] = {
            key: authentication[key]
            for key in ("required", "principal", "auth_method", "scopes")
            if key in authentication
        }
    protocol = payload.get("mcp_protocol")
    if isinstance(protocol, dict):
        summary["mcp_protocol"] = {
            key: protocol[key]
            for key in ("latest", "supported")
            if key in protocol
        }
    if summary.get("server") != "cluster-mcp":
        raise MCPClientError("MCP endpoint is not a TS cluster-mcp server")
    return summary


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {_redact_text(str(key)): _sanitize(item) for key, item in value.items()}
    return value


def _redact_text(value: str) -> str:
    redacted = value
    token = os.environ.get("TS_CLUSTER_MCP_TOKEN")
    if token:
        redacted = redacted.replace(token, "[REDACTED]")
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", redacted)
    return redacted
