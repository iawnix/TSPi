from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ts_compute import mcp_diagnostics
from ts_remote.mcp import MCPClientError, MCPConnectionSettings, SDKToolCaller, TSClusterMCPClient


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "diagnostic-secret-token-value-1234567890"


class _Caller:
    def __init__(self, responses: dict[str, dict[str, object] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return response


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
                "software": {
                    "software": [
                        {
                            "name": "gaussian",
                            "kind": "profile",
                            "command": ["/private/gaussian16-run"],
                            "activation_script": "/private/activate.sh",
                            "activation_script_exists": True,
                            "allowed_queues": ["batch"],
                            "requires_gpu": False,
                        }
                    ],
                    "load_errors": {},
                },
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
    assert result["capabilities"]["software"] == {
        "profiles": [
            {
                "name": "gaussian",
                "kind": "profile",
                "activation_script_exists": True,
                "allowed_queues": ["batch"],
                "requires_gpu": False,
            }
        ],
        "load_error_names": [],
    }
    assert "/private/gaussian16-run" not in json.dumps(result)
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


def test_mcp_node_probe_calls_only_list_nodes(monkeypatch) -> None:
    nodes = [{"name": "compute-0-1", "state": "free", "ncpus_free_total": "24/24"}]
    caller = _Caller({"list_nodes": {"nodes": nodes}})
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("nodes")

    assert result["ok"] is True
    assert result["nodes"] == nodes
    assert caller.calls == [("list_nodes", {})]


def test_mcp_cluster_probe_combines_only_read_only_scheduler_views(monkeypatch) -> None:
    capabilities = {
        "server": "cluster-mcp",
        "scheduler": "torque",
        "allowed_queues": ["batch"],
    }
    queues = [
        {
            "name": "batch",
            "allowed_for_submission": True,
            "enabled": "True",
            "started": "True",
            "total_jobs": 3,
        }
    ]
    nodes = [
        {
            "name": "compute-0-1",
            "state": "free",
            "ncpus_free_total": "24/24",
            "ngpus_free_total": "0/0",
            "running_jobs": 0,
            "jobs": ["unbounded-detail"],
        }
    ]
    caller = _Caller(
        {
            "cluster_capabilities": capabilities,
            "list_queues": {"queues": queues},
            "list_nodes": {"nodes": nodes},
        }
    )
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("cluster")

    assert result["ok"] is True
    assert result["partial"] is False
    assert result["capabilities"]["scheduler"] == "torque"
    assert result["queue_summary"] == {
        "total_queues": 1,
        "allowed_for_submission": 1,
        "gpu_queues": 0,
        "enabled": 1,
        "started": 1,
        "reported_total_jobs": 3,
    }
    assert result["node_summary"]["total_nodes"] == 1
    assert result["node_summary"]["cpu"] == {
        "reported_nodes": 1,
        "free": 24,
        "total": 24,
        "nodes_with_free": 1,
    }
    assert "nodes" not in result
    assert "queues" not in result
    assert "unbounded-detail" not in json.dumps(result)
    assert caller.calls == [
        ("cluster_capabilities", {}),
        ("list_queues", {}),
        ("list_nodes", {}),
    ]


def test_mcp_cluster_probe_retains_partial_results(monkeypatch) -> None:
    caller = _Caller(
        {
            "cluster_capabilities": {"server": "cluster-mcp", "scheduler": "torque"},
            "list_queues": MCPClientError("queue probe failed"),
            "list_nodes": {"nodes": [{"state": "free", "ncpus_free_total": "8/16"}]},
        }
    )
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("cluster")

    assert result["ok"] is False
    assert result["partial"] is True
    assert result["components"] == {"capabilities": "pass", "queues": "fail", "nodes": "pass"}
    assert result["errors"]["queues"]["class"] == "protocol_error"
    assert result["node_summary"]["cpu"]["free"] == 8


def test_mcp_cluster_probe_output_is_bounded_by_aggregation(monkeypatch) -> None:
    nodes = [
        {
            "name": f"compute-{index}",
            "state": "free" if index % 2 == 0 else "job-exclusive",
            "ncpus_free_total": "8/16",
            "jobs": [f"job-{index}-{item}" for item in range(20)],
        }
        for index in range(500)
    ]
    caller = _Caller(
        {
            "cluster_capabilities": {"server": "cluster-mcp", "scheduler": "torque"},
            "list_queues": {"queues": []},
            "list_nodes": {"nodes": nodes},
        }
    )
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(mcp_diagnostics, "_client", lambda _settings: TSClusterMCPClient(caller))

    result = mcp_diagnostics.diagnose_mcp("cluster")
    serialized = json.dumps(result)

    assert result["node_summary"]["total_nodes"] == 500
    assert result["node_summary"]["cpu"]["total"] == 8000
    assert len(serialized) < 3000
    assert "compute-499" not in serialized
    assert "job-499-19" not in serialized


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


def test_sdk_tool_caller_exposes_task_group_leaf_for_diagnostics(monkeypatch) -> None:
    caller = SDKToolCaller(_settings())

    async def fail(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ConnectionResetError("peer reset during MCP response")],
        )

    monkeypatch.setattr(caller, "_call_tool", fail)
    monkeypatch.setattr(mcp_diagnostics, "_connection_settings", _settings)
    monkeypatch.setattr(
        mcp_diagnostics,
        "_client",
        lambda _settings: TSClusterMCPClient(caller),
    )

    result = mcp_diagnostics.diagnose_mcp("doctor")

    assert result["ok"] is False
    assert result["error"]["class"] == "connection_failed"
    assert "ConnectionResetError: peer reset during MCP response" in result["error"]["message"]
    assert "unhandled errors in a TaskGroup" not in result["error"]["message"]
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
