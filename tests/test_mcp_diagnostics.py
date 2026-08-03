from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ts_compute import mcp_diagnostics
from ts_remote.mcp import MCPClientError, MCPConnectionSettings, TSClusterMCPClient


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "diagnostic-secret-token-value-1234567890"


class _Caller:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return self.responses[name]


class _FailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def capabilities(self) -> dict[str, object]:
        raise self.error


def _settings() -> MCPConnectionSettings:
    return MCPConnectionSettings("http://127.0.0.1:8765/mcp", token=TOKEN, timeout_seconds=12)


def test_mcp_status_returns_only_compact_safe_capabilities(monkeypatch) -> None:
    caller = _Caller(
        {
            "cluster_capabilities": {
                "server": "cluster-mcp",
                "version": "2.0.0",
                "scheduler": "openpbs",
                "workspace": "/cluster/principals/pi-ts",
                "authentication": {
                    "principal": "pi-ts",
                    "auth_method": "http-bearer",
                    "scopes": ["cluster:read", "ts:submit"],
                    "token": TOKEN,
                },
                "allowed_queues": ["batch"],
                "private_server_field": TOKEN,
            }
        }
    )
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("status")

    assert result["ok"] is True
    assert result["capabilities"]["server"] == "cluster-mcp"
    assert result["capabilities"]["authentication"]["principal"] == "pi-ts"
    assert "token" not in result["capabilities"]["authentication"]
    assert "private_server_field" not in result["capabilities"]
    assert TOKEN not in json.dumps(result)
    assert caller.calls == [("cluster_capabilities", {})]


def test_mcp_queue_probe_calls_only_list_queues(monkeypatch) -> None:
    queues = [{"name": "batch", "allowed_for_submission": True, "total_jobs": 3}]
    caller = _Caller({"list_queues": {"queues": queues}})
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("queues")

    assert result["ok"] is True
    assert result["queues"] == queues
    assert caller.calls == [("list_queues", {})]


def test_mcp_doctor_classifies_and_redacts_authentication_failure(monkeypatch) -> None:
    monkeypatch.setenv("TS_CLUSTER_MCP_TOKEN", TOKEN)
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(
        mcp_diagnostics,
        "_client",
        lambda _settings: _FailingClient(MCPClientError(f"HTTP 401 Unauthorized Bearer {TOKEN}")),
    )

    result = mcp_diagnostics.diagnose_mcp("doctor")

    assert result["ok"] is False
    assert result["error"]["class"] == "authentication_failed"
    assert result["checks"]["authentication"] == "fail"
    serialized = json.dumps(result)
    assert TOKEN not in serialized
    assert "[REDACTED]" in serialized


def test_mcp_doctor_classifies_timeout(monkeypatch) -> None:
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: _FailingClient(TimeoutError("timed out")))

    result = mcp_diagnostics.diagnose_mcp("doctor")

    assert result["error"]["class"] == "timeout"
    assert result["checks"]["connection"] == "fail"


def test_mcp_diagnostic_cli_requires_no_workspace_and_never_echoes_token(tmp_path: Path) -> None:
    env = {**os.environ, "TS_CLUSTER_MCP_TOKEN": TOKEN}
    env.pop("TS_CLUSTER_MCP_URL", None)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ts_compute.py"), "mcp-diagnostic", "--mode", "doctor"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["error"]["class"] == "configuration_missing"
    assert TOKEN not in completed.stdout
