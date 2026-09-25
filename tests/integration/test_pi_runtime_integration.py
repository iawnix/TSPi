from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = {
    "system.prompt",
    "research.read",
    "research.change",
    "research.continuation",
    "research.strategy",
    "research.interpretation",
    "research.checkpoint",
    "research.strategy",
    "research.interpretation",
    "research.checkpoint",
    "review.run",
    "review.respond",
    "compute.run",
    "compute.environment",
    "artifact.seed",
    "artifact.compare",
    "analysis.run",
    "execution.dispatch",
    "artifact.import",
    "artifact.render",
    "report.build",
}


def test_real_pi_offline_loads_extensions_and_public_inventory(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    agent_dir = tmp_path / "pi-agent"
    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_OFFLINE": "1",
        "TS_AGENT_PYTHON": sys.executable,
        "TS_WORKSPACE_ROOT": str(workspace),
    }
    installed = subprocess.run(
        [pi, "install", "-l", str(ROOT), "--approve"],
        cwd=workspace,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    completed = subprocess.run(
        [
            pi,
            "--mode", "rpc",
            "--offline",
            "--no-session",
            "--session-dir", str(tmp_path / "pi-sessions"),
            "--no-context-files",
            "--no-builtin-tools",
            "--approve",
            "--extension", str(ROOT / "tools" / "test" / "probes" / "pi_inventory_probe.ts"),
        ],
        cwd=workspace,
        env=env,
        input=json.dumps({"id": "inventory", "type": "prompt", "message": "/ts-test-inventory"}) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    message = _notification(completed.stdout, "TS_TEST_INVENTORY:")
    inventory = json.loads(message.split(":", 1)[1])
    assert set(inventory["active"]) == EXPECTED_TOOLS
    assert EXPECTED_TOOLS <= set(inventory["all"])
    assert not {"ts_compute", "ts_subagent_render", "ts_subagent_report"} & set(inventory["all"])


def test_real_pi_review_uses_named_result_tool_without_provider_strict(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    with _RecordingServer(requests, [_tool_call_chunks("ts_review_result", _review_result())]) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_review_probe(pi, workspace, agent_dir, tmp_path / "sessions", "TS_TEST_REVIEW:")

    assert completed.returncode == 0, completed.stderr
    message = _notification(completed.stdout, "TS_TEST_REVIEW:")
    result = json.loads(message.split(":", 1)[1])
    assert result["result"]["role"] == "review"
    assert result["result"]["scope"]["node_refs"][0].startswith("node_")
    assert result["metadata"]["operation"] == "claim_review"
    assert len(requests) == 1
    function = requests[0]["tools"][0]["function"]
    assert function["name"] == "ts_review_result"
    assert function.get("strict") is not True
    assert requests[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "ts_review_result"},
    }
    assert set(function["parameters"]["properties"]) == {
        "outcome", "summary", "facts", "missing_evidence", "conflicts", "options", "limitations"
    }


def test_real_pi_review_reads_one_artifact_batch_then_forces_result(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    artifact_bytes = b"normal termination\nmode follows the proposed coordinate\n"
    (workspace / "review-artifact.log").write_bytes(artifact_bytes)
    artifact_id = "art_" + hashlib.sha256(artifact_bytes).hexdigest()[:24]
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    responses = [
        _tool_call_chunks(
            "ts_review_artifact_read",
            {"requests": [{"artifact_id": artifact_id, "section": "overview"}]},
        ),
        _tool_call_chunks("ts_review_result", _review_result()),
    ]
    with _RecordingServer(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_review_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            "TS_TEST_REVIEW:",
            command="/ts-test-review-child artifact",
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(_notification(completed.stdout, "TS_TEST_REVIEW:").split(":", 1)[1])
    assert len(requests) == 2
    assert {item["function"]["name"] for item in requests[0]["tools"]} == {
        "ts_review_artifact_read",
        "ts_review_result",
    }
    assert "tool_choice" not in requests[0]
    assert requests[1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "ts_review_result"},
    }
    assert len(result["actions"]) == 1
    assert result["actions"][0]["action"] == "artifact_read"
    assert "path" not in result["actions"][0]
    assert "text" not in result["actions"][0]
    assert result["metadata"]["artifact_read_count"] == 1


def test_real_pi_review_surfaces_provider_502_without_format_retry(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    error = _HttpError(502, {"error": {"type": "server_error", "code": "internal_server_error", "message": "Bad gateway"}})
    with _RecordingServer(requests, [error]) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_review_probe(pi, workspace, agent_dir, tmp_path / "sessions", "TS_TEST_REVIEW_ERROR:")

    assert completed.returncode == 0, completed.stderr
    message = _notification(completed.stdout, "TS_TEST_REVIEW_ERROR:")
    assert "provider request failed" in message
    assert "502" in message
    assert "internal_server_error" in message
    assert "without calling ts_review_result" not in message
    assert len(requests) == 1


def test_real_pi_review_preserves_artifact_read_audit_on_provider_failure(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    artifact_bytes = b"normal termination\n"
    (workspace / "review-artifact.log").write_bytes(artifact_bytes)
    artifact_id = "art_" + hashlib.sha256(artifact_bytes).hexdigest()[:24]
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    error = _HttpError(502, {"error": {"type": "server_error", "code": "internal_server_error", "message": "Bad gateway"}})
    with _RecordingServer(requests, [
        _tool_call_chunks(
            "ts_review_artifact_read",
            {"requests": [{"artifact_id": artifact_id, "section": "overview"}]},
        ),
        error,
    ]) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_review_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            "TS_TEST_REVIEW_ERROR:",
            command="/ts-test-review-child artifact",
        )

    assert completed.returncode == 0, completed.stderr
    failure = json.loads(_notification(completed.stdout, "TS_TEST_REVIEW_ERROR:").split(":", 1)[1])
    assert "provider request failed" in failure["message"]
    assert len(failure["actions"]) == 1
    assert failure["actions"][0]["action"] == "artifact_read"
    assert "text" not in failure["actions"][0]
    assert len(requests) == 2
    assert requests[1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "ts_review_result"},
    }


@pytest.mark.parametrize(
    ("scenario", "action_names"),
    [
        ("launch", ["ts_workspace_compute_prepare", "ts_workspace_compute_submit"]),
        ("inspect-tail", ["ts_workspace_compute_status", "ts_workspace_compute_tail"]),
        ("finalize", ["ts_workspace_compute_collect", "ts_workspace_compute_parse"]),
    ],
)
def test_real_pi_compute_executes_fixed_plan_and_derives_result(
    tmp_path: Path,
    scenario: str,
    action_names: list[str],
) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    before = _canonical_files(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    responses = [
        *[_tool_call_chunks(name, {}, call_id=f"call_action_{index}") for index, name in enumerate(action_names)],
        _tool_call_chunks("ts_compute_result", _compute_result(), call_id="call_compute_result"),
    ]
    with _RecordingServer(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_compute_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            scenario,
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(_notification(completed.stdout, "TS_TEST_COMPUTE:").split(":", 1)[1])
    assert result["result"]["role"] == "compute"
    assert result["result"]["authority"] == "operational"
    assert result["result"]["payload"]["completed_actions"] == [name.rsplit("_", 1)[-1] for name in action_names]
    assert result["metadata"]["action_names"] == action_names
    assert [action["tool"] for action in result["actions"]] == action_names
    assert len(requests) == len(action_names) + 1
    for request in requests:
        assert all(tool["function"].get("strict") is not True for tool in request["tools"])
    assert "tool_choice" not in requests[-2]
    assert requests[-1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "ts_compute_result"},
    }
    assert _canonical_files(workspace) == before


@pytest.mark.parametrize(
    ("scenario", "action_names"),
    [
        ("launch-ambiguous", ["ts_workspace_compute_prepare", "ts_workspace_compute_submit"]),
        ("cancel-ambiguous", ["ts_workspace_compute_cancel"]),
    ],
)
def test_real_pi_compute_never_replays_ambiguous_controls(
    tmp_path: Path,
    scenario: str,
    action_names: list[str],
) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    responses = [
        *[_tool_call_chunks(name, {}, call_id=f"call_ambiguous_{index}") for index, name in enumerate(action_names)],
        _tool_call_chunks("ts_compute_result", _compute_result(), call_id="call_compute_result"),
    ]
    with _RecordingServer(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_compute_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            scenario,
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(_notification(completed.stdout, "TS_TEST_COMPUTE:").split(":", 1)[1])
    assert [action["tool"] for action in result["actions"]] == action_names
    assert result["result"]["outcome"] == "partial"
    assert result["result"]["payload"]["action_outcome"] == "unknown"
    assert result["result"]["payload"]["reconciliation_required"] is True
    assert len(requests) == len(action_names) + 1
    assert requests[-1]["tool_choice"]["function"]["name"] == "ts_compute_result"


def test_real_pi_compute_recovers_from_premature_result_call(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    responses = [
        _tool_call_chunks("ts_compute_result", _compute_result(), call_id="call_premature_result"),
        _tool_call_chunks("ts_workspace_compute_prepare", {}, call_id="call_prepare_after_result"),
        _tool_call_chunks("ts_workspace_compute_submit", {}, call_id="call_submit_after_result"),
        _tool_call_chunks("ts_compute_result", _compute_result(), call_id="call_final_result"),
    ]
    with _RecordingServer(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_compute_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            "launch",
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(_notification(completed.stdout, "TS_TEST_COMPUTE:").split(":", 1)[1])
    assert result["metadata"]["result_attempts"] == 2
    assert [action["tool"] for action in result["actions"]] == [
        "ts_workspace_compute_prepare",
        "ts_workspace_compute_submit",
    ]
    assert len(requests) == 4
    assert "tool_choice" not in requests[1]
    assert "tool_choice" not in requests[2]
    assert requests[3]["tool_choice"]["function"]["name"] == "ts_compute_result"


def test_real_pi_compute_surfaces_provider_502_before_result_contract_error(tmp_path: Path) -> None:
    pi = _supported_pi()
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    requests: list[dict[str, object]] = []
    error = _HttpError(502, {"error": {"type": "server_error", "code": "internal_server_error", "message": "Bad gateway"}})
    with _RecordingServer(requests, [error]) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_compute_probe(
            pi,
            workspace,
            agent_dir,
            tmp_path / "sessions",
            "cancel",
        )

    assert completed.returncode == 0, completed.stderr
    failure = json.loads(_notification(completed.stdout, "TS_TEST_COMPUTE_ERROR:").split(":", 1)[1])
    assert "provider request failed" in failure["message"]
    assert "502" in failure["message"]
    assert "internal_server_error" in failure["message"]
    assert "Compute ended" not in failure["message"]
    assert failure["actions"] == []
    assert len(requests) == 1


def _supported_pi() -> str:
    configured = os.environ.get("PI_TEST_BINARY")
    candidates = [
        configured,
        shutil.which("pi"),
        str(Path.home() / ".npm-global" / "bin" / "pi"),
        "/home/iaw/soft/Pi/current/root/bin/pi",
    ]
    pi = next((value for value in candidates if value and Path(value).is_file()), None)
    if pi is None:
        pytest.skip("Pi executable is not installed")
    version = subprocess.run([pi, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    parsed = tuple(map(int, match.groups())) if match else (0, 0, 0)
    if parsed < (0, 81, 1):
        pytest.skip(f"Pi {version.strip()} is older than the supported integration surface")
    return pi


def _run_review_probe(
    pi: str,
    workspace: Path,
    agent_dir: Path,
    session_dir: Path,
    prefix: str,
    *,
    command: str = "/ts-test-review-child",
) -> SimpleNamespace:
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1"}
    return _run_rpc_until(
        [
            pi,
            "--mode", "rpc",
            "--offline",
            "--no-session",
            "--session-dir", str(session_dir),
            "--no-context-files",
            "--no-skills",
            "--no-extensions",
            "--no-builtin-tools",
            "--approve",
            "--extension", str(ROOT / "tools" / "test" / "probes" / "pi_review_probe.ts"),
        ],
        workspace,
        env,
        {"id": "review", "type": "prompt", "message": command},
        prefix,
    )


def _run_compute_probe(
    pi: str,
    workspace: Path,
    agent_dir: Path,
    session_dir: Path,
    scenario: str,
) -> SimpleNamespace:
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1"}
    return _run_rpc_until(
        [
            pi,
            "--mode", "rpc",
            "--offline",
            "--no-session",
            "--session-dir", str(session_dir),
            "--no-context-files",
            "--no-skills",
            "--no-extensions",
            "--no-builtin-tools",
            "--approve",
            "--extension", str(ROOT / "tools" / "test" / "probes" / "pi_compute_probe.ts"),
        ],
        workspace,
        env,
        {"id": "compute", "type": "prompt", "message": f"/ts-test-compute-child {scenario}"},
        "TS_TEST_COMPUTE",
    )


def _run_rpc_until(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    command: dict[str, object],
    prefix: str,
) -> SimpleNamespace:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(json.dumps(command) + "\n")
    process.stdin.flush()
    lines: list[str] = []
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            lines.append(line)
            if prefix in line:
                break
        process.stdin.close()
        returncode = process.wait(timeout=10)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    lines.extend(process.stdout.readlines())
    return SimpleNamespace(returncode=returncode, stdout="".join(lines), stderr=process.stderr.read())


def _notification(stdout: str, prefix: str) -> str:
    for line in stdout.splitlines():
        if not line.strip().startswith("{"):
            continue
        row = json.loads(line)
        message = str(row.get("message", ""))
        if row.get("type") == "extension_ui_request" and message.startswith(prefix):
            return message
    raise AssertionError({"prefix": prefix, "stdout": stdout})


def _write_recording_model(agent_dir: Path, base_url: str) -> None:
    value = {
        "providers": {
            "ts-recording": {
                "baseUrl": f"{base_url}/v1",
                "api": "openai-completions",
                "apiKey": "recording-key",
                "models": [{
                    "id": "recording-model",
                    "name": "TS Recording Model",
                    "reasoning": False,
                    "input": ["text"],
                    "contextWindow": 32000,
                    "maxTokens": 4096,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                }],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(value), encoding="utf-8")


def _review_result() -> dict[str, object]:
    return {
        "outcome": "partial",
        "summary": "The bounded graph is insufficient for a final mechanism conclusion.",
        "facts": [],
        "missing_evidence": ["One discriminating observation is missing."],
        "conflicts": [],
        "options": [{
            "action": "Collect one discriminating observation.",
            "discriminator": "It should distinguish the competing predictions.",
            "risks": ["The result may remain inconclusive."],
        }],
        "limitations": ["Recording-provider integration test."],
    }


def _compute_result() -> dict[str, object]:
    return {
        "summary": "The fixed Compute lifecycle reached a terminal operational result.",
        "limitations": ["Recording-provider integration test."],
    }


def _tool_call_chunks(
    name: str,
    arguments: dict[str, object],
    *,
    call_id: str = "call_review_001",
) -> list[dict[str, object]]:
    return [
        {
            "id": "chatcmpl-tool",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "tool_calls": [{
                    "index": 0,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }]},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-tool",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
    ]


def _canonical_files(workspace: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(workspace.glob("*.json"))}


class _HttpError:
    def __init__(self, status: int, body: dict[str, object]) -> None:
        self.status = status
        self.body = body


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]]
    responses: list[object]

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        index = len(self.requests)
        self.requests.append(request)
        response = self.responses[index]
        if isinstance(response, _HttpError):
            payload = json.dumps(response.body).encode()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in response) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _RecordingServer:
    def __init__(self, requests: list[dict[str, object]], responses: list[object]) -> None:
        handler = type("RecordingHandler", (_RecordingHandler,), {"requests": requests, "responses": responses})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
