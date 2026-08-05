from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "ts_workspace_context",
    "ts_workspace_decision_draft",
    "ts_workspace_decision_validate",
    "ts_workspace_decision_apply",
    "ts_subagent_review",
    "ts_subagent_compute",
    "ts_mcp_inspect",
    "ts_subagent_render",
    "ts_subagent_report",
    "ts_subagent_email_draft",
}


def test_real_pi_offline_loads_extensions_and_public_tool_inventory(tmp_path: Path) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    version = subprocess.run(
        [pi, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    if _version_tuple(version) < (0, 81, 1):
        pytest.skip(f"Pi {version} is older than the supported integration surface")

    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(tmp_path / "pi-agent"),
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
    settings = json.loads((workspace / ".pi" / "settings.json").read_text(encoding="utf-8"))
    assert len(settings["packages"]) == 1
    assert (workspace / settings["packages"][0]).resolve() == ROOT

    command = [
        pi,
        "--mode",
        "rpc",
        "--offline",
        "--no-session",
        "--session-dir",
        str(tmp_path / "pi-sessions"),
        "--no-context-files",
        "--no-builtin-tools",
        "--approve",
        "--extension",
        str(ROOT / "tests" / "pi_inventory_probe.ts"),
    ]

    completed = subprocess.run(
        command,
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
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    notification = next(
        row
        for row in rows
        if row.get("type") == "extension_ui_request"
        and row.get("method") == "notify"
        and str(row.get("message", "")).startswith("TS_TEST_INVENTORY:")
    )
    inventory = json.loads(notification["message"].split(":", 1)[1])
    assert set(inventory["active"]) == EXPECTED_TOOLS
    assert EXPECTED_TOOLS <= set(inventory["all"])
    assert "ts_workspace_compute_submit" not in inventory["all"]
    assert "ts_workspace_compute_cancel" not in inventory["all"]
    assert "ts_workspace_email_send" not in inventory["all"]


def test_real_pi_render_child_session_uses_only_bound_tool(tmp_path: Path) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    (workspace / "inputs").mkdir(exist_ok=True)
    (workspace / "inputs" / "reactant.xyz").write_text("1\nR\nH 0 0 0\n", encoding="utf-8")
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()

    requests: list[dict[str, object]] = []
    responses = [_tool_call_chunks("ts_workspace_render_execute"), _render_result_chunks()]
    with _recording_server(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_child_probe(
            pi=pi,
            workspace=workspace,
            agent_dir=agent_dir,
            session_dir=tmp_path / "pi-sessions",
            extension=ROOT / "tests" / "pi_child_probe.ts",
            command="/ts-test-child",
            notification_prefix="TS_TEST_CHILD:",
        )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    errors = [row for row in rows if str(row.get("message", "")).startswith("TS_TEST_CHILD_ERROR:")]
    assert not errors, errors
    notification = next(
        (
            row
            for row in rows
            if row.get("type") == "extension_ui_request"
            and str(row.get("message", "")).startswith("TS_TEST_CHILD:")
        ),
        None,
    )
    assert notification is not None, {"stdout": completed.stdout, "stderr": completed.stderr, "requests": requests}
    result = json.loads(notification["message"].split(":", 1)[1])
    assert result["report"]["payload"]["output_ref"] == "nodes/n000/outputs/recording.png"
    assert result["metadata"]["action_names"] == ["ts_workspace_render_execute"]
    assert len(requests) == 2
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["ts_workspace_render_execute"]
    assert "Execute this bounded render operation" in requests[0]["messages"][-1]["content"][0]["text"]
    assert any(message.get("role") == "tool" for message in requests[1]["messages"])


def test_real_pi_report_child_loads_private_report_skill_and_bound_tool(tmp_path: Path) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()

    requests: list[dict[str, object]] = []
    responses = [_tool_call_chunks("ts_workspace_report_build"), _report_result_chunks()]
    with _recording_server(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_child_probe(
            pi=pi,
            workspace=workspace,
            agent_dir=agent_dir,
            session_dir=tmp_path / "pi-sessions",
            extension=ROOT / "tests" / "pi_report_probe.ts",
            command="/ts-test-report-child",
            notification_prefix="TS_TEST_REPORT:",
        )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    errors = [row for row in rows if str(row.get("message", "")).startswith("TS_TEST_REPORT_ERROR:")]
    assert not errors, errors
    notification = next(
        (
            row
            for row in rows
            if row.get("type") == "extension_ui_request"
            and str(row.get("message", "")).startswith("TS_TEST_REPORT:")
        ),
        None,
    )
    assert notification is not None, {"stdout": completed.stdout, "stderr": completed.stderr, "requests": requests}
    result = json.loads(notification["message"].split(":", 1)[1])
    assert result["report"]["payload"]["package_ref"] == "reports/recording-report"
    assert result["metadata"]["action_names"] == ["ts_workspace_report_build"]
    assert len(requests) == 2
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["ts_workspace_report_build"]
    assert "Research Report Operator" in json.dumps(requests[0]["messages"])


def test_real_pi_review_child_session_has_no_tools(tmp_path: Path) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()

    requests: list[dict[str, object]] = []
    with _recording_server(requests, [_review_result_chunks()]) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_child_probe(
            pi=pi,
            workspace=workspace,
            agent_dir=agent_dir,
            session_dir=tmp_path / "pi-sessions",
            extension=ROOT / "tests" / "pi_review_probe.ts",
            command="/ts-test-review-child",
            notification_prefix="TS_TEST_REVIEW:",
        )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    errors = [row for row in rows if str(row.get("message", "")).startswith("TS_TEST_REVIEW_ERROR:")]
    assert not errors, errors
    notification = next(
        (
            row
            for row in rows
            if row.get("type") == "extension_ui_request"
            and str(row.get("message", "")).startswith("TS_TEST_REVIEW:")
        ),
        None,
    )
    assert notification is not None, {"stdout": completed.stdout, "stderr": completed.stderr, "requests": requests}
    result = json.loads(notification["message"].split(":", 1)[1])
    assert result["result"]["role"] == "review"
    assert result["metadata"]["review_type"] == "mechanism"
    assert len(requests) == 1
    assert not requests[0].get("tools")
    assert "Review this bounded TS workspace task packet" in requests[0]["messages"][-1]["content"][0]["text"]


def test_real_pi_compute_child_session_uses_only_bound_prepare_tool(tmp_path: Path) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()

    requests: list[dict[str, object]] = []
    responses = [_tool_call_chunks("ts_workspace_compute_prepare"), _compute_result_chunks()]
    with _recording_server(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
        completed = _run_child_probe(
            pi=pi,
            workspace=workspace,
            agent_dir=agent_dir,
            session_dir=tmp_path / "pi-sessions",
            extension=ROOT / "tests" / "pi_compute_probe.ts",
            command="/ts-test-compute-child",
            notification_prefix="TS_TEST_COMPUTE:",
        )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    errors = [row for row in rows if str(row.get("message", "")).startswith("TS_TEST_COMPUTE_ERROR:")]
    assert not errors, errors
    notification = next(
        (
            row
            for row in rows
            if row.get("type") == "extension_ui_request"
            and str(row.get("message", "")).startswith("TS_TEST_COMPUTE:")
        ),
        None,
    )
    assert notification is not None, {"stdout": completed.stdout, "stderr": completed.stderr, "requests": requests}
    result = json.loads(notification["message"].split(":", 1)[1])
    assert result["report"]["payload"]["backend"] == "gaussian"
    assert result["metadata"]["action_names"] == ["ts_workspace_compute_prepare"]
    assert len(requests) == 2
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["ts_workspace_compute_prepare"]
    assert "Execute this bounded compute operation" in requests[0]["messages"][-1]["content"][0]["text"]
    assert any(message.get("role") == "tool" for message in requests[1]["messages"])


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_real_pi_public_subagent_emits_ui_lifecycle_updates(tmp_path: Path, outcome: str) -> None:
    pi = _pi_binary()
    if pi is None:
        pytest.skip("Pi executable is not installed")
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    agent_dir = tmp_path / "pi-agent"
    agent_dir.mkdir()
    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_OFFLINE": "1",
        "TS_AGENT_PYTHON": sys.executable,
        "TS_WORKSPACE_ROOT": str(workspace),
    }
    requests: list[dict[str, object]] = []
    child_response = _review_result_for_request if outcome == "success" else _invalid_review_result
    responses = [
        _tool_call_chunks(
            "ts_subagent_review",
            {"reviewType": "mechanism", "question": "Review the bounded mechanism evidence.", "nodeId": "n000"},
        ),
        child_response,
        _assistant_text_chunks("The bounded review call finished."),
    ]
    with _recording_server(requests, responses) as base_url:
        _write_recording_model(agent_dir, base_url)
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
        completed = _run_rpc_until(
            [
                pi,
                "--mode",
                "rpc",
                "--offline",
                "--no-session",
                "--session-dir",
                str(tmp_path / "pi-sessions"),
                "--no-context-files",
                "--no-builtin-tools",
                "--approve",
                "--model",
                "ts-recording/recording-model",
            ],
            cwd=workspace,
            env=env,
            command={"id": "lifecycle", "type": "prompt", "message": "Run the bounded mechanism review now."},
            notification_prefix='"type":"agent_end"',
            timeout=45,
        )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    status_texts = [
        str(row["statusText"])
        for row in rows
        if row.get("type") == "extension_ui_request"
        and row.get("method") == "setStatus"
        and row.get("statusKey") == "ts-subagent"
        and row.get("statusText")
    ]
    phases = [next(phase for phase in ("preflight", "starting", "running", "validating", "completed", "failed", "cancelled") if phase in text) for text in status_texts]
    deduplicated = [phase for index, phase in enumerate(phases) if index == 0 or phase != phases[index - 1]]
    expected = ["preflight", "starting", "running", "validating", "completed" if outcome == "success" else "failed"]
    assert deduplicated == expected, {"stdout": completed.stdout, "stderr": completed.stderr, "requests": requests}
    assert len(requests) == 3


def _pi_binary() -> str | None:
    configured = os.environ.get("PI_TEST_BINARY")
    if configured:
        return configured
    discovered = shutil.which("pi")
    if discovered:
        return discovered
    fallback = Path.home() / ".npm-global" / "bin" / "pi"
    return str(fallback) if fallback.is_file() else None


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def _run_rpc_until(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    command: dict[str, object],
    notification_prefix: str,
    timeout: float,
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
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write(json.dumps(command) + "\n")
    process.stdin.flush()
    stdout_lines: list[str] = []
    deadline = time.monotonic() + timeout
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
            stdout_lines.append(line)
            if notification_prefix in line:
                break
        process.stdin.close()
        returncode = process.wait(timeout=10)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    stdout_lines.extend(process.stdout.readlines())
    return SimpleNamespace(
        returncode=returncode,
        stdout="".join(stdout_lines),
        stderr=process.stderr.read(),
    )


def _run_child_probe(
    *,
    pi: str,
    workspace: Path,
    agent_dir: Path,
    session_dir: Path,
    extension: Path,
    command: str,
    notification_prefix: str,
) -> SimpleNamespace:
    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_OFFLINE": "1",
    }
    return _run_rpc_until(
        [
            pi,
            "--mode",
            "rpc",
            "--offline",
            "--no-session",
            "--session-dir",
            str(session_dir),
            "--no-context-files",
            "--no-skills",
            "--no-extensions",
            "--no-builtin-tools",
            "--approve",
            "--extension",
            str(extension),
        ],
        cwd=workspace,
        env=env,
        command={"id": "child", "type": "prompt", "message": command},
        notification_prefix=notification_prefix,
        timeout=45,
    )


def _write_recording_model(agent_dir: Path, base_url: str) -> None:
    config = {
        "providers": {
            "ts-recording": {
                "baseUrl": f"{base_url}/v1",
                "api": "openai-completions",
                "apiKey": "recording-key",
                "models": [
                    {
                        "id": "recording-model",
                        "name": "TS Recording Model",
                        "reasoning": False,
                        "input": ["text"],
                        "contextWindow": 32000,
                        "maxTokens": 4096,
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    }
                ],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(config), encoding="utf-8")


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]]
    responses: list[object]

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        response_index = len(self.requests)
        self.requests.append(body)
        if response_index >= len(self.responses):
            self.send_error(500, "recording response sequence exhausted")
            return
        configured = self.responses[response_index]
        response = configured(body) if callable(configured) else configured
        payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in response) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _RecordingServer:
    def __init__(
        self,
        requests: list[dict[str, object]],
        responses: list[object],
    ) -> None:
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


def _recording_server(
    requests: list[dict[str, object]],
    responses: list[object],
) -> _RecordingServer:
    return _RecordingServer(requests, responses)


def _tool_call_chunks(tool_name: str, arguments: dict[str, object] | None = None) -> list[dict[str, object]]:
    return [
        {
            "id": "chatcmpl-tool",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_recording_001",
                                "type": "function",
                                "function": {"name": tool_name, "arguments": json.dumps(arguments or {})},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-tool",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
    ]


def _render_result_chunks() -> list[dict[str, object]]:
    scope = {
        "report_id": "rep_recording_001",
        "node_ids": ["n000"],
        "hypothesis_id": None,
        "pathway_id": None,
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": "agent_recording_001",
        "role": "render",
        "authority": "operational",
        "operation": "render",
        "outcome": "success",
        "summary": "The bound recording render completed.",
        "scope": scope,
        "facts": [],
        "artifact_refs": ["nodes/n000/outputs/recording.png"],
        "program": None,
        "payload": {
            "operation": "render",
            "node_id": "n000",
            "output_ref": "nodes/n000/outputs/recording.png",
        },
        "limitations": ["Recording-provider integration test."],
        "provenance": {},
    }
    return _assistant_result_chunks(report)


def _report_result_chunks() -> list[dict[str, object]]:
    package_ref = "reports/recording-report"
    scope = {
        "report_id": "rep_report_001",
        "node_ids": [],
        "hypothesis_id": None,
        "pathway_id": None,
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": "agent_report_001",
        "role": "report",
        "authority": "operational",
        "operation": "build",
        "outcome": "success",
        "summary": "The bound recording report build completed.",
        "scope": scope,
        "facts": [],
        "artifact_refs": [
            f"{package_ref}/final_report.md",
            f"{package_ref}/report_context.json",
            f"{package_ref}/email_summary.md",
            f"{package_ref}/assets",
            f"{package_ref}/package_manifest.json",
        ],
        "program": None,
        "payload": {
            "operation": "build",
            "package_ref": package_ref,
            "report_ref": f"{package_ref}/final_report.md",
            "context_ref": f"{package_ref}/report_context.json",
            "email_summary_ref": f"{package_ref}/email_summary.md",
            "assets_ref": f"{package_ref}/assets",
            "manifest_ref": f"{package_ref}/package_manifest.json",
            "manifest_digest": "sha256:" + "5" * 64,
            "workspace_revision": "sha256:" + "6" * 64,
        },
        "limitations": ["Recording-provider integration test."],
        "provenance": {},
    }
    return _assistant_result_chunks(report)


def _review_result_chunks(
    *,
    task_id: str = "agent_review_001",
    scope: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    scope = scope or {
        "report_id": "rep_review_001",
        "node_ids": ["n000"],
        "hypothesis_id": None,
        "pathway_id": None,
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": task_id,
        "role": "review",
        "authority": "advisory",
        "operation": "mechanism",
        "outcome": "partial",
        "summary": "The bounded context is insufficient for a mechanism conclusion.",
        "scope": scope,
        "facts": [],
        "artifact_refs": [],
        "program": None,
        "payload": {
            "missing_evidence": ["Primary mechanism evidence was not included."],
            "conflicts": [],
            "options": [
                {
                    "action": "Request one discriminating primary artifact.",
                    "discriminator": "The artifact should distinguish the competing mechanism predictions.",
                    "risks": ["No scientific status can be assigned from this review."],
                }
            ],
        },
        "limitations": ["Recording-provider integration test."],
        "provenance": {},
    }
    return _assistant_result_chunks(report)


def _review_result_for_request(request: dict[str, object]) -> list[dict[str, object]]:
    messages = request.get("messages")
    assert isinstance(messages, list) and messages
    content = messages[-1].get("content")
    if isinstance(content, list):
        prompt = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    else:
        prompt = str(content or "")
    packet = json.loads(prompt.split("\n\n", 1)[1])
    return _review_result_chunks(task_id=packet["task_id"], scope=packet["scope"])


def _invalid_review_result(_request: dict[str, object]) -> list[dict[str, object]]:
    return _assistant_text_chunks('{"invalid":true}')


def _assistant_text_chunks(text: str) -> list[dict[str, object]]:
    return [
        {
            "id": "chatcmpl-text",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-text",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]


def _compute_result_chunks() -> list[dict[str, object]]:
    intent_id = "intent_recording_001"
    artifact_ref = f"nodes/n000/attempts/{intent_id}/prepared.json"
    scope = {
        "report_id": "rep_compute_001",
        "node_ids": ["n000"],
        "hypothesis_id": None,
        "pathway_id": None,
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": "agent_compute_001",
        "role": "backend",
        "authority": "operational",
        "operation": "prepare",
        "outcome": "success",
        "summary": "The bound Gaussian preparation completed without running a job.",
        "scope": scope,
        "facts": [
            {
                "kind": "program",
                "layer": None,
                "statement": "The calculation intent was prepared but not executed.",
                "status": "observed",
                "basis_refs": [artifact_ref],
            }
        ],
        "artifact_refs": [artifact_ref],
        "program": {"outcome": "not_run", "state": "prepared", "error_class": None, "exit_status": None},
        "payload": {"intent_id": intent_id, "node_id": "n000", "backend": "gaussian"},
        "limitations": ["No calculation was submitted."],
        "provenance": {},
    }
    return _assistant_result_chunks(report)


def _assistant_result_chunks(report: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "id": "chatcmpl-result",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": json.dumps(report)},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-result",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "recording-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
