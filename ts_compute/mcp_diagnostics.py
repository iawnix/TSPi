"""Read-only diagnostics for the host-side TS Cluster MCP connection."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from ts_remote.mcp import MCPClientError, MCPConnectionSettings, SDKToolCaller, TSClusterMCPClient


MCP_DIAGNOSTIC_MODES = frozenset({"status", "doctor", "queues", "nodes", "cluster"})
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
        elif mode == "nodes":
            result = {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "ok": True,
                "connection": connection,
                "nodes": client.list_nodes()["nodes"],
            }
        elif mode == "cluster":
            result = _cluster_summary(client, connection)
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


def _cluster_summary(
    client: TSClusterMCPClient,
    connection: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "cluster",
        "connection": connection,
        "components": {},
    }
    errors: dict[str, dict[str, str]] = {}

    try:
        result["capabilities"] = _capability_summary(client.capabilities())
        result["components"]["capabilities"] = "pass"
    except Exception as exc:
        result["components"]["capabilities"] = "fail"
        errors["capabilities"] = _component_error(exc)

    try:
        result["queue_summary"] = _queue_summary(client.list_queues()["queues"])
        result["components"]["queues"] = "pass"
    except Exception as exc:
        result["components"]["queues"] = "fail"
        errors["queues"] = _component_error(exc)

    try:
        result["node_summary"] = _node_summary(client.list_nodes()["nodes"])
        result["components"]["nodes"] = "pass"
    except Exception as exc:
        result["components"]["nodes"] = "fail"
        errors["nodes"] = _component_error(exc)

    passed = sum(value == "pass" for value in result["components"].values())
    result["ok"] = not errors
    result["partial"] = bool(errors) and passed > 0
    if errors:
        result["errors"] = errors
    return result


def _component_error(error: Exception) -> dict[str, str]:
    return {
        "class": _classify_error(error, "probe"),
        "message": _redact_text(str(error) or type(error).__name__),
    }


def _queue_summary(queues: list[dict[str, Any]]) -> dict[str, Any]:
    total_jobs = [_integer(queue.get("total_jobs")) for queue in queues]
    reported_jobs = [value for value in total_jobs if value is not None]
    return {
        "total_queues": len(queues),
        "allowed_for_submission": sum(queue.get("allowed_for_submission") is True for queue in queues),
        "gpu_queues": sum(queue.get("is_gpu_queue") is True for queue in queues),
        "enabled": sum(_truthy(queue.get("enabled")) for queue in queues),
        "started": sum(_truthy(queue.get("started")) for queue in queues),
        "reported_total_jobs": sum(reported_jobs) if reported_jobs else None,
    }


def _node_summary(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    cpu_pairs: list[tuple[int, int]] = []
    gpu_pairs: list[tuple[int, int]] = []
    running_jobs: list[int] = []
    for node in nodes:
        state = str(node.get("state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        cpu = _free_total(node.get("ncpus_free_total"))
        if cpu is not None:
            cpu_pairs.append(cpu)
        gpu = _free_total(node.get("ngpus_free_total"))
        if gpu is not None:
            gpu_pairs.append(gpu)
        running = _integer(node.get("running_jobs"))
        if running is not None:
            running_jobs.append(running)
    return {
        "total_nodes": len(nodes),
        "state_counts": dict(sorted(state_counts.items())),
        "cpu": _resource_summary(cpu_pairs),
        "gpu": _resource_summary(gpu_pairs),
        "reported_running_jobs": sum(running_jobs) if running_jobs else None,
    }


def _resource_summary(pairs: list[tuple[int, int]]) -> dict[str, int]:
    return {
        "reported_nodes": len(pairs),
        "free": sum(free for free, _total in pairs),
        "total": sum(total for _free, total in pairs),
        "nodes_with_free": sum(free > 0 for free, _total in pairs),
    }


def _free_total(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split("/", 1)
    if len(parts) != 2:
        return None
    free, total = (_integer(part.strip()) for part in parts)
    if free is None or total is None or free > total:
        return None
    return free, total


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


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
