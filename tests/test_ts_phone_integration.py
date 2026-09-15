from __future__ import annotations

import fcntl
import json
import os
import shutil
import select
import subprocess
from pathlib import Path

import pytest

from tests.runtime_helpers import write_test_runtime_manifest, write_test_suite_manifest


ROOT = Path(__file__).resolve().parents[1]
TSPI = ROOT / "TSPi"
PHONE_POLICY = ROOT / "extensions" / "ts-phone-bridge" / "policy.ts"
PHONE_PROTOCOL = ROOT / "extensions" / "ts-phone-bridge" / "protocol.ts"
PHONE_CLIENT = ROOT / "extensions" / "ts-phone-bridge" / "bridge-client.ts"
PHONE_EXTENSION = ROOT / "extensions" / "ts-phone-bridge" / "index.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
PACKAGE_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def _copy_launcher(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    package_home = install_root / ".pi" / "packages" / "tspi"
    suite_root = package_home / "releases" / "test-suite"
    package_root = suite_root / "agent"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"name": "@iawnix/ts-agent", "version": PACKAGE_VERSION}) + "\n",
        encoding="utf-8",
    )
    write_test_suite_manifest(suite_root, version=PACKAGE_VERSION)
    shutil.copy2(TSPI, package_root / "TSPi")
    (package_root / "TSPi").chmod(0o755)
    (package_root / "scripts").mkdir()
    for name in ("_bootstrap.py", "tspi_host.py", "pi-loader.mjs"):
        shutil.copy2(ROOT / "scripts" / name, package_root / "scripts" / name)
    shutil.copytree(
        ROOT / "packages" / "ts-agent-kernel",
        package_root / "packages" / "ts-agent-kernel",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    shutil.copy2(ROOT / "environment.yml", package_root / "environment.yml")
    shutil.copy2(ROOT / "requirements-runtime.txt", package_root / "requirements-runtime.txt")
    write_test_runtime_manifest(package_root, install_root)
    (package_home / "current").symlink_to("releases/test-suite")
    launcher = install_root / "TSPi"
    launcher.symlink_to(".pi/packages/tspi/current/agent/TSPi")
    return install_root, launcher


def test_standalone_phone_starts_visible_bridged_tui(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'mode': os.environ.get('TS_PHONE_MODE'), "
        "'workspace': os.environ.get('TS_PHONE_WORKSPACE_ID'), "
        "'access': os.environ.get('TS_PHONE_ACCESS_MODE')}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    completed = subprocess.run(
        [str(launcher), "--standalone", "--workspace", "reaction-phone", "--phone"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mode"] == "bridge"
    assert result["workspace"] == "reaction-phone"
    assert result["access"] == "controller"
    assert "--session-id" in result["args"]
    assert "--continue" not in result["args"]
    assert "--mode" not in result["args"]
    assert any(value.endswith("/extensions/ts-phone-bridge/index.ts") for value in result["args"])
    assert (install_root / "workspaces" / "reaction-phone" / ".pi" / "settings.json").is_file()


def test_second_phone_session_requires_explicit_observer_mode(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    controller_pi = tmp_path / "controller-pi.py"
    controller_pi.write_text(
        "#!/usr/bin/env python3\nprint('ready', flush=True)\ninput()\n",
        encoding="utf-8",
    )
    controller_pi.chmod(0o755)
    observer_pi = tmp_path / "observer-pi.py"
    observer_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'access': os.environ.get('TS_PHONE_ACCESS_MODE')}))\n",
        encoding="utf-8",
    )
    observer_pi.chmod(0o755)

    holder = subprocess.Popen(
        [str(launcher), "--standalone", "--workspace", "shared-phone"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(controller_pi)},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        conflict = subprocess.run(
            [str(launcher), "--standalone", "--workspace", "shared-phone", "--phone"],
            cwd=install_root,
            env={**os.environ, "PI_BIN": str(observer_pi)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert conflict.returncode == 1
        assert "another Root Agent already owns" in conflict.stderr
        observer = subprocess.run(
            [str(launcher), "--standalone", "--workspace", "shared-phone", "--phone", "--phone-access", "observer"],
            cwd=install_root, env={**os.environ, "PI_BIN": str(observer_pi)},
            capture_output=True, text=True, timeout=10,
        )
        assert observer.returncode == 0, observer.stderr
        result = json.loads(observer.stdout)
        assert result["access"] == "observer"
        assert "--continue" not in result["args"]
        assert "--session-id" in result["args"]
    finally:
        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        holder.communicate(timeout=5)


def test_tspi_phone_worker_starts_exact_rpc_session(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    fake_pi = tmp_path / "node"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'mode': os.environ.get('TS_PHONE_MODE'), "
        "'access': os.environ.get('TS_PHONE_ACCESS_MODE'), 'offline': os.environ.get('PI_OFFLINE')}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    completed = subprocess.run(
        [
            str(launcher),
            "--workspace", "reaction-phone",
            "--phone-worker",
            "--session-id", "session_4",
            "--phone-access", "controller",
            "--name", "IRC follow-up",
            "--model", "cpa/gpt-5.6-sol",
        ],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi), "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", "")},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mode"] == "bridge"
    assert result["access"] == "controller"
    assert result["offline"] == "1"
    assert result["args"][result["args"].index("--mode") + 1] == "rpc"
    assert result["args"][result["args"].index("--session-id") + 1] == "session_4"
    assert result["args"][result["args"].index("--name") + 1] == "IRC follow-up"
    assert result["args"][result["args"].index("--model") + 1] == "cpa/gpt-5.6-sol"
    assert "--continue" not in result["args"]
    assert (install_root / "workspaces" / "reaction-phone" / "workspace.json").is_file()


def test_tspi_phone_observer_cannot_initialize_a_workspace(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    workspace.mkdir(parents=True)
    fake_pi = tmp_path / "unexpected-pi.py"
    fake_pi.write_text("#!/usr/bin/env python3\nraise SystemExit(99)\n", encoding="utf-8")
    fake_pi.chmod(0o755)

    completed = subprocess.run(
        [
            str(launcher),
            "--workspace", "reaction-phone",
            "--phone-worker",
            "--session-id", "session_2",
            "--phone-access", "observer",
        ],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 1
    assert "workspace bootstrap must finish" in completed.stderr
    assert list(workspace.iterdir()) == []


def test_tspi_phone_worker_rejects_incomplete_internal_contract(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    rejected = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--phone-worker"],
        cwd=install_root,
        env=os.environ,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert rejected.returncode == 2
    assert "requires a valid --session-id" in rejected.stderr


def test_tspi_lifecycle_preflight_is_read_only_and_structured(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    workspace.mkdir(parents=True)

    completed = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--lifecycle-preflight"],
        cwd=install_root,
        env=os.environ,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "schema_version": "ts-phone-project-preflight/2",
        "workspace_root": str(workspace),
        "root_agent_active": False,
        "session_writers_active": False,
        "session_guard_contract": "tspi-session-guard/1",
        "remote_calculations": 0,
        "unresolved_remote_effects": 0,
    }
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("occupied", [False, True])
def test_lifecycle_preflight_checks_kernel_lock_not_stale_pid(tmp_path: Path, occupied: bool) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    (workspace / ".pi").mkdir(parents=True)
    lock = workspace / ".pi" / "root-agent.lock"
    lock.write_text("pid=999999999\n", encoding="utf-8")
    with lock.open("r+") as holder:
        if occupied:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [str(launcher), "--workspace", "reaction-phone", "--lifecycle-preflight"],
            cwd=install_root, capture_output=True, text=True, timeout=10,
        )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["root_agent_active"] is occupied
    assert lock.read_text(encoding="utf-8") == "pid=999999999\n"


@pytest.mark.parametrize("unsafe_path", ["lock_symlink", "pi_symlink", "fifo"])
def test_lifecycle_preflight_rejects_unsafe_lock_paths(tmp_path: Path, unsafe_path: str) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    (workspace / ".pi").mkdir(parents=True)
    lock = workspace / ".pi" / "root-agent.lock"
    if unsafe_path == "lock_symlink":
        lock.symlink_to(tmp_path / "absent-lock")
    elif unsafe_path == "pi_symlink":
        (workspace / ".pi").rmdir()
        (workspace / ".pi").symlink_to(tmp_path / "absent-pi")
    else:
        os.mkfifo(lock)
    result = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--lifecycle-preflight"],
        cwd=install_root, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""


def test_lifecycle_guard_holds_writer_lock_until_host_closes_stdin(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    workspace.mkdir(parents=True)
    guard = subprocess.Popen(
        [str(launcher), "--workspace", "reaction-phone", "--lifecycle-guard"],
        cwd=install_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert guard.stdout is not None
        assert select.select([guard.stdout], [], [], 10)[0], "guard did not acknowledge"
        reply = json.loads(guard.stdout.readline())
        assert reply["schema_version"] == "ts-phone-project-guard/1"
        assert reply["guard_acquired"] is True
        assert reply["root_agent_active"] is False
        assert not (workspace / "workspace.json").exists()
        with (workspace / ".pi" / "root-agent.lock").open("r+") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            blocked = subprocess.run(
                [str(launcher), "--standalone", "--workspace", "reaction-phone"],
                cwd=install_root, capture_output=True, text=True, timeout=10,
            )
            assert blocked.returncode == 1
            assert "session writer or lifecycle operation is active" in blocked.stderr
            assert not (workspace / "workspace.json").exists()
            guard.communicate(timeout=5)
            assert guard.returncode == 0
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if guard.poll() is None:
            guard.kill()
            guard.communicate(timeout=5)


def test_tspi_lifecycle_preflight_fails_closed_on_operational_integrity_error(
    tmp_path: Path,
) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    workspace = install_root / "workspaces" / "reaction-phone"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside-nodes"
    outside.mkdir()
    (workspace / "nodes").symlink_to(outside, target_is_directory=True)

    completed = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--lifecycle-preflight"],
        cwd=install_root,
        env={**os.environ, "TS_REMOTE_CONFIG": str(tmp_path / "not-present.toml")},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 1
    assert "operational state cannot be verified for deletion" in completed.stderr


def test_phone_policy_allows_controller_tools_and_restricts_observers() -> None:
    script = f"""
import {{ authorizeTsPhoneTool }} from {json.dumps(PHONE_POLICY.as_uri())};
process.stdout.write(JSON.stringify({{
  controllerBash: authorizeTsPhoneTool("controller", "bash") ?? null,
  controllerWrite: authorizeTsPhoneTool("controller", "write") ?? null,
  controllerUnknown: authorizeTsPhoneTool("controller", "new_tool") ?? null,
  observerRead: authorizeTsPhoneTool("observer", "read") ?? null,
  observerSystemPrompt: authorizeTsPhoneTool("observer", "sys_prompt") ?? null,
  observerWrite: authorizeTsPhoneTool("observer", "write") ?? null,
  observerUnknown: authorizeTsPhoneTool("observer", "new_tool") ?? null,
}}));
"""
    result = _node_json(script)
    assert result["controllerBash"] is None
    assert result["controllerWrite"] is None
    assert result["controllerUnknown"] is None
    assert result["observerRead"] is None
    assert result["observerSystemPrompt"] is None
    assert result["observerWrite"]["block"] is True
    assert result["observerUnknown"]["block"] is True


def test_phone_bridge_protocol_rejects_raw_rpc_records() -> None:
    script = f"""
import {{ parseBridgeServerRecord }} from {json.dumps(PHONE_PROTOCOL.as_uri())};
let rawRpcError;
try {{ parseBridgeServerRecord({{ protocolVersion: "ts-phone-bridge/3", type: "prompt", message: "x" }}); }}
catch (error) {{ rawRpcError = error.message; }}
const command = parseBridgeServerRecord({{
  protocolVersion: "ts-phone-bridge/3",
  type: "command.prompt",
  workspaceId: "ts_006",
  sessionId: "session-1",
  instanceEpoch: "epoch-1",
  sessionGeneration: 2,
  requestId: "request-1",
  clientMessageId: "client-1",
  message: "hello",
}});
let missingAgentRunIdError;
try {{
  parseBridgeServerRecord({{
    protocolVersion: "ts-phone-bridge/3",
    type: "command.abort",
    workspaceId: "ts_006",
    sessionId: "session-1",
    instanceEpoch: "epoch-1",
    sessionGeneration: 2,
    requestId: "abort-request-1",
  }});
}} catch (error) {{ missingAgentRunIdError = error.message; }}
const abortCommand = parseBridgeServerRecord({{
  protocolVersion: "ts-phone-bridge/3",
  type: "command.abort",
  workspaceId: "ts_006",
  sessionId: "session-1",
  instanceEpoch: "epoch-1",
  sessionGeneration: 2,
  requestId: "abort-request-2",
  agentRunId: "run-2-4",
}});
process.stdout.write(JSON.stringify({{
  rawRpcError,
  command,
  missingAgentRunIdError,
  abortCommand,
}}));
"""
    result = _node_json(script)
    assert result["rawRpcError"]
    assert result["command"]["message"] == "hello"
    assert "agentRunId" in result["missingAgentRunIdError"]
    assert result["abortCommand"]["agentRunId"] == "run-2-4"


def test_phone_bridge_abort_guard_binds_the_active_agent_run() -> None:
    script = f"""
import {{ abortCommandRejection, buildAgentRunId }} from {json.dumps(PHONE_EXTENSION.as_uri())};
const active = buildAgentRunId(3, 7);
process.stdout.write(JSON.stringify({{
  active,
  accepted: abortCommandRejection(false, active, active) ?? null,
  idle: abortCommandRejection(true, active, active),
  missing: abortCommandRejection(false, undefined, active),
  stale: abortCommandRejection(false, active, "run-3-6"),
}}));
"""
    result = _node_json(script)
    assert result == {
        "active": "run-3-7",
        "accepted": None,
        "idle": "agent_not_running",
        "missing": "agent_not_running",
        "stale": "agent_run_stale",
    }


def test_phone_bridge_lifecycle_exposes_and_enforces_agent_run_id(tmp_path: Path) -> None:
    socket_path = tmp_path / "lifecycle-bridge.sock"
    secret_path = tmp_path / "lifecycle-bridge.secret"
    secret_path.write_text("B" * 43 + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    script = f"""
import {{ createServer }} from "node:net";
import {{ unlink }} from "node:fs/promises";
import installTsPhoneBridge from {json.dumps(PHONE_EXTENSION.as_uri())};
const socketPath = {json.dumps(str(socket_path))};
const received = [];
let peer;
const server = createServer((socket) => {{
  peer = socket;
  let buffer = "";
  socket.setEncoding("utf8");
  socket.on("data", (chunk) => {{
    buffer += chunk;
    while (true) {{
      const newline = buffer.indexOf("\\n");
      if (newline < 0) break;
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const record = JSON.parse(line);
      received.push(record);
      if (record.type === "bridge.register") {{
        socket.write(JSON.stringify({{
          protocolVersion: "ts-phone-bridge/3",
          type: "bridge.registered",
          workspaceId: "ts_006",
          sessionId: "session-1",
          instanceEpoch: record.instanceEpoch,
        }}) + "\\n");
      }}
    }}
  }});
}});
await new Promise((resolve, reject) => {{ server.once("error", reject); server.listen(socketPath, resolve); }});
process.env.TS_PHONE_MODE = "bridge";
process.env.TS_PHONE_WORKSPACE_ID = "ts_006";
process.env.TS_PHONE_ACCESS_MODE = "controller";
process.env.TS_PHONE_BRIDGE_SOCKET = socketPath;
process.env.TS_PHONE_BRIDGE_SECRET_FILE = {json.dumps(str(secret_path))};
const handlers = {{}};
const pi = {{
  on: (name, handler) => {{ handlers[name] = handler; }},
  sendUserMessage: () => {{}},
}};
installTsPhoneBridge(pi);
let idle = true;
let abortCount = 0;
const ctx = {{
  sessionManager: {{
    getSessionId: () => "session-1",
    getSessionName: () => "TS 006",
    getBranch: () => [],
  }},
  ui: {{ setStatus: () => {{}} }},
  model: undefined,
  getContextUsage: () => undefined,
  thinkingLevel: "off",
  isIdle: () => idle,
  abort: () => {{ abortCount += 1; }},
}};
await handlers.session_start({{ type: "session_start", reason: "startup" }}, ctx);
async function waitFor(predicate) {{
  const deadline = Date.now() + 5000;
  while (!predicate()) {{
    if (Date.now() >= deadline) throw new Error("timeout");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }}
}}
await waitFor(() => received.some((record) => record.type === "session.snapshot"));
idle = false;
await handlers.agent_start({{ type: "agent_start" }}, ctx);
await waitFor(() => received.filter((record) => record.type === "session.snapshot").length >= 2);
const startEvent = received.find((record) =>
  record.type === "event.publish" && record.eventType === "agent_start");
const runningSnapshot = received.findLast((record) =>
  record.type === "session.snapshot" && record.snapshot.agentRunId);
const agentRunId = startEvent.payload.agentRunId;
await handlers.agent_start({{ type: "agent_start" }}, ctx);
await waitFor(() => received.filter((record) => record.eventType === "agent_start").length === 2);
const retryEvent = received.findLast((record) => record.eventType === "agent_start");
const commandBase = {{
  protocolVersion: "ts-phone-bridge/3",
  workspaceId: "ts_006",
  sessionId: "session-1",
  instanceEpoch: received.find((record) => record.type === "bridge.register").instanceEpoch,
  sessionGeneration: 1,
  type: "command.abort",
}};
peer.write(JSON.stringify({{
  ...commandBase,
  requestId: "abort-stale",
  agentRunId: "run-1-99",
}}) + "\\n");
await waitFor(() => received.some((record) => record.type === "command.ack" && record.requestId === "abort-stale"));
peer.write(JSON.stringify({{
  ...commandBase,
  requestId: "abort-active",
  agentRunId,
}}) + "\\n");
await waitFor(() => received.some((record) => record.type === "command.ack" && record.requestId === "abort-active"));
idle = true;
await handlers.agent_settled({{ type: "agent_settled" }}, ctx);
await waitFor(() => received.findLast((record) => record.type === "session.snapshot")?.snapshot.isStreaming === false);
peer.write(JSON.stringify({{
  ...commandBase,
  requestId: "abort-idle",
  agentRunId,
}}) + "\\n");
await waitFor(() => received.some((record) => record.type === "command.ack" && record.requestId === "abort-idle"));
const settledEvent = received.find((record) =>
  record.type === "event.publish" && record.eventType === "agent_settled");
const settledSnapshot = received.filter((record) => record.type === "session.snapshot").at(-1);
const ack = (requestId) => received.find((record) =>
  record.type === "command.ack" && record.requestId === requestId);
await handlers.session_shutdown({{ type: "session_shutdown", reason: "quit" }}, ctx);
await new Promise((resolve) => server.close(resolve));
await unlink(socketPath).catch(() => {{}});
process.stdout.write(JSON.stringify({{
  agentRunId,
  startPayload: startEvent.payload,
  retryPayload: retryEvent.payload,
  runningSnapshotIsStreaming: runningSnapshot.snapshot.isStreaming,
  runningSnapshotAgentRunId: runningSnapshot.snapshot.agentRunId,
  settledPayload: settledEvent.payload,
  settledSnapshotIsStreaming: settledSnapshot.snapshot.isStreaming,
  settledSnapshotHasAgentRunId: Object.hasOwn(settledSnapshot.snapshot, "agentRunId"),
  staleAck: ack("abort-stale"),
  activeAck: ack("abort-active"),
  idleAck: ack("abort-idle"),
  abortCount,
}}));
"""
    result = _node_json(script)
    assert result["agentRunId"] == "run-1-1"
    assert result["startPayload"] == {
        "type": "agent_start",
        "origin": "unknown",
        "turnId": "turn-1-2",
        "agentRunId": result["agentRunId"],
        "attempt": 1,
    }
    assert result["retryPayload"] == {**result["startPayload"], "attempt": 2}
    assert result["runningSnapshotIsStreaming"] is True
    assert result["runningSnapshotAgentRunId"] == result["agentRunId"]
    assert result["settledPayload"] == {
        "type": "agent_settled",
        "origin": "unknown",
        "turnId": "turn-1-2",
        "agentRunId": result["agentRunId"],
        "attempt": 2,
        "outcome": {"status": "cancelled"},
    }
    assert result["settledSnapshotIsStreaming"] is False
    assert result["settledSnapshotHasAgentRunId"] is False
    assert result["staleAck"]["ok"] is False
    assert result["staleAck"]["errorCode"] == "agent_run_stale"
    assert result["activeAck"]["ok"] is True
    assert result["idleAck"]["ok"] is False
    assert result["idleAck"]["errorCode"] == "agent_not_running"
    assert result["abortCount"] == 1


def test_phone_bridge_snapshot_exposes_stable_message_cursors() -> None:
    script = f"""
import {{ buildSnapshotMessagePage }} from {json.dumps(PHONE_EXTENSION.as_uri())};
const entries = Array.from({{ length: 510 }}, (_, index) => ({{
  type: "message",
  id: index.toString(16).padStart(8, "0"),
  message: {{
    role: "assistant",
    content: [{{ type: "text", text: `message-${{index}}` }}],
    timestamp: index,
  }},
}}));
const page = buildSnapshotMessagePage(entries);
const oversized = buildSnapshotMessagePage([{{
  type: "message",
  id: "ffffffff",
  message: {{
    role: "assistant",
    content: [{{
      type: "toolCall",
      name: "large-tool",
      arguments: {{ payload: "x".repeat(6 * 1024 * 1024) }},
    }}],
    timestamp: 1,
  }},
}}]);
process.stdout.write(JSON.stringify({{
  count: page.messages.length,
  firstId: page.messageIds[0],
  lastId: page.messageIds.at(-1),
  hasMore: page.hasMore,
  nextBefore: page.nextBefore,
  firstMessage: page.messages[0],
  oversizedCount: oversized.messages.length,
  oversizedHasMore: oversized.hasMore,
}}));
"""
    result = _node_json(script)
    assert result["count"] == 500
    assert result["firstId"] == "0000000a"
    assert result["lastId"] == "000001fd"
    assert result["hasMore"] is True
    assert result["nextBefore"] == "0000000a"
    assert "message-10" in json.dumps(result["firstMessage"])
    assert result["oversizedCount"] == 0
    assert result["oversizedHasMore"] is False


def test_phone_bridge_runtime_snapshot_uses_pi_context_usage() -> None:
    script = f"""
import {{ buildSessionRuntimeSnapshot }} from {json.dumps(PHONE_EXTENSION.as_uri())};
const model = {{ provider: "cpa", id: "gpt-5.6-sol" }};
const measured = buildSessionRuntimeSnapshot(
  model,
  {{ tokens: 78214, contextWindow: 128000, percent: 61.1046875 }},
  "2026-08-31T06:32:18.000Z",
);
const afterCompaction = buildSessionRuntimeSnapshot(
  model,
  {{ tokens: null, contextWindow: 128000, percent: null }},
  "2026-08-31T06:33:18.000Z",
);
process.stdout.write(JSON.stringify({{
  measured,
  afterCompaction,
  missingModel: buildSessionRuntimeSnapshot(undefined, undefined) ?? null,
}}));
"""
    result = _node_json(script)
    assert result["measured"] == {
        "schemaVersion": "ts-phone-session-runtime/1",
        "model": {"provider": "cpa", "id": "gpt-5.6-sol"},
        "context": {
            "usedTokens": 78214,
            "limitTokens": 128000,
            "measurement": "pi_estimate",
        },
        "updatedAt": "2026-08-31T06:32:18.000Z",
    }
    assert result["afterCompaction"]["context"]["usedTokens"] is None
    assert result["missingModel"] is None


def test_phone_model_recovery_waits_for_registry_and_preserves_explicit_selection() -> None:
    script = f"""
import {{ restorePhoneModel, phonePromptProblem, projectMessage, buildSessionRuntimeSnapshot }} from {json.dumps(PHONE_EXTENSION.as_uri())};
const log = [];
const ctx = {{
  model: {{ id: "unknown", provider: "unknown" }},
  sessionManager: {{ getBranch: () => [{{ type: "model_change", provider: "cpa", modelId: "saved" }}] }},
  modelRegistry: {{
    async refresh() {{ await new Promise(r => setTimeout(r, 5)); log.push("refreshed"); }},
    getError() {{ return undefined; }},
    find(provider, id) {{ log.push("find:" + id); return {{ provider, id }}; }},
    hasConfiguredAuth() {{ return true; }},
  }},
}};
let defaultReads = 0;
const defaults = async () => {{ defaultReads++; return {{ provider: "cpa", modelId: "default" }}; }};
const pi = {{ async setModel(model) {{ ctx.model = model; log.push("selected:" + model.id); return true; }} }};
await restorePhoneModel(pi, ctx, defaults);
const saved = {{ log: [...log], model: ctx.model, defaultReads, problem: phonePromptProblem(ctx) ?? null }};
ctx.model = {{ id: "unknown", provider: "unknown" }};
ctx.sessionManager.getBranch = () => [];
await restorePhoneModel(pi, ctx, defaults);
const fresh = {{ model: ctx.model, defaultReads }};
ctx.model = {{ id: "unknown", provider: "unknown" }};
ctx.sessionManager.getBranch = () => [{{ type: "model_change", provider: "cpa", modelId: "removed" }}];
ctx.modelRegistry.find = () => undefined;
await restorePhoneModel(pi, ctx, defaults);
const missing = {{ model: ctx.model, defaultReads, problem: phonePromptProblem(ctx) }};
ctx.model = {{ id: "saved", provider: "cpa" }};
ctx.modelRegistry.hasConfiguredAuth = () => false;
const noAuth = phonePromptProblem(ctx);
const failed = projectMessage({{ role: "assistant", content: [], stopReason: "error", errorMessage: "private credential" }});
process.stdout.write(JSON.stringify({{ saved, fresh, missing, noAuth, failed,
  unknownRuntime: buildSessionRuntimeSnapshot({{ provider: "unknown", id: "unknown" }}, undefined) ?? null,
}}));
"""
    result = _node_json(script)
    assert result["saved"]["log"] == ["refreshed", "find:saved", "selected:saved"]
    assert result["saved"]["defaultReads"] == 0
    assert result["saved"]["problem"] is None
    assert result["fresh"]["model"]["id"] == "default"
    assert result["missing"]["defaultReads"] == 1
    assert result["missing"]["problem"] == "model_unavailable"
    assert result["noAuth"] == "model_auth_missing"
    assert result["failed"]["outputState"] == "failed"
    assert "private credential" not in json.dumps(result)
    assert result["unknownRuntime"] is None


def test_phone_model_readiness_preserves_storage_errors_without_leaking_details() -> None:
    script = f"""
import {{ restorePhoneModel, phonePromptProblem }} from {json.dumps(PHONE_EXTENSION.as_uri())};
const model = {{ provider: "cpa", id: "configured" }};
let error = "Availability refresh: EROFS auth.json.lock private-test-key";
let selected = 0;
const ctx = {{
  model: undefined,
  sessionManager: {{ getBranch: () => [] }},
  modelRegistry: {{
    async refresh() {{}},
    getError: () => error,
    find: () => model,
    hasConfiguredAuth: () => false,
  }},
}};
const pi = {{ async setModel() {{ selected++; return true; }} }};
const defaults = async () => ({{ provider: "cpa", modelId: "configured" }});
const storage = await restorePhoneModel(pi, ctx, defaults);
const snapshot = phonePromptProblem(ctx);
ctx.modelRegistry.refresh = async () => {{ throw Object.assign(new Error("private-test-key"), {{ code: "EACCES" }}); }};
const thrown = await restorePhoneModel(pi, ctx, defaults);
ctx.modelRegistry.refresh = async () => {{}};
error = undefined;
const missingAuth = await restorePhoneModel(pi, ctx, defaults);
ctx.modelRegistry.hasConfiguredAuth = () => true;
pi.setModel = async () => false;
const rejectedSelection = await restorePhoneModel(pi, ctx, defaults);
ctx.model = model;
error = "An unrelated provider has invalid configuration";
const healthySelection = phonePromptProblem(ctx);
process.stdout.write(JSON.stringify({{ storage, snapshot, thrown, missingAuth, rejectedSelection, selected,
  healthySelection: healthySelection ?? null }}));
"""
    result = _node_json(script)
    assert result["storage"] == "model_storage_unavailable"
    assert result["snapshot"] == "model_storage_unavailable"
    assert result["thrown"] == "model_storage_unavailable"
    assert result["missingAuth"] == "model_auth_missing"
    assert result["rejectedSelection"] == "model_check_failed"
    assert result["selected"] == 0
    assert result["healthySelection"] is None
    assert "private-test-key" not in json.dumps(result)


def test_child_model_readiness_uses_the_same_safe_diagnostics() -> None:
    helper = ROOT / "extensions" / "shared" / "model-readiness.ts"
    script = f"""
import {{ requireRuntimeModel }} from {json.dumps(helper.as_uri())};
const selected = {{ provider: "recording", id: "test-model" }};
const storageError = new Error("private-test-key", {{ cause: {{ code: "EROFS" }} }});
const results = {{}};
for (const mode of ["healthy", "unavailable", "auth", "storage", "thrown", "other"]) {{
  const runtime = {{
    getModel() {{ return mode === "unavailable" ? undefined : selected; }},
    hasConfiguredAuth() {{
      if (mode === "thrown") throw storageError;
      return mode === "healthy";
    }},
    getError() {{
      return mode === "storage" ? storageError : mode === "other" ? "private-test-key" : undefined;
    }},
  }};
  try {{ results[mode] = requireRuntimeModel(runtime, selected); }}
  catch (error) {{ results[mode] = error.message; }}
}}
process.stdout.write(JSON.stringify(results));
"""
    result = _node_json(script)
    assert result["healthy"] == {"provider": "recording", "id": "test-model"}
    for mode, code in {
        "unavailable": "model_unavailable",
        "auth": "model_auth_missing",
        "storage": "model_storage_unavailable",
        "thrown": "model_storage_unavailable",
        "other": "model_check_failed",
    }.items():
        assert result[mode].startswith(code + ": ")
    assert "private-test-key" not in json.dumps(result)


def test_phone_bridge_client_exchanges_events_commands_and_approval(tmp_path: Path) -> None:
    socket_path = tmp_path / "bridge.sock"
    secret_path = tmp_path / "bridge.secret"
    secret_path.write_text("A" * 43 + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    script = f"""
import {{ createServer }} from "node:net";
import {{ unlink }} from "node:fs/promises";
import {{ TsPhoneBridgeClient }} from {json.dumps(PHONE_CLIENT.as_uri())};
const socketPath = {json.dumps(str(socket_path))};
const received = [];
const commands = [];
let promptAck = false;
let approvalAck = false;
let approvalResult;
let resolveDone;
const done = new Promise((resolve) => {{ resolveDone = resolve; }});
function maybeDone() {{ if (promptAck && approvalAck) resolveDone(); }}
const server = createServer((socket) => {{
  let buffer = "";
  socket.setEncoding("utf8");
  socket.on("data", (chunk) => {{
    buffer += chunk;
    while (true) {{
      const newline = buffer.indexOf("\\n");
      if (newline < 0) break;
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const record = JSON.parse(line);
      received.push(record);
      const base = {{
        protocolVersion: "ts-phone-bridge/3",
        workspaceId: "ts_006",
        sessionId: "session-1",
        instanceEpoch: record.instanceEpoch,
      }};
      if (record.type === "bridge.register") {{
        socket.write(JSON.stringify({{ ...base, type: "bridge.registered" }}) + "\\n");
      }} else if (record.type === "session.snapshot") {{
        socket.write(JSON.stringify({{
          ...base,
          type: "command.prompt",
          sessionGeneration: 1,
          requestId: "prompt-request",
          clientMessageId: "phone-message-1",
          message: "hello from phone",
        }}) + "\\n");
      }} else if (record.type === "approval.request") {{
        socket.write(JSON.stringify({{
          ...base,
          type: "approval.respond",
          sessionGeneration: 1,
          requestId: "approval-response",
          approvalId: record.approvalId,
          approved: true,
        }}) + "\\n");
      }} else if (record.type === "command.ack" && record.requestId === "prompt-request") {{
        promptAck = record.ok;
        maybeDone();
      }} else if (record.type === "command.ack" && record.requestId === "approval-response") {{
        approvalAck = record.ok;
        maybeDone();
      }}
    }}
  }});
}});
await new Promise((resolve, reject) => {{ server.once("error", reject); server.listen(socketPath, resolve); }});
const client = new TsPhoneBridgeClient({{
  workspaceId: "ts_006",
  workspaceRoot: "/tmp/ts_006",
  accessMode: "controller",
  socketPath,
  secretPath: {json.dumps(str(secret_path))},
  getSessionId: () => "session-1",
  getSessionGeneration: () => 1,
  onCommand: (command) => {{ commands.push(command); }},
  onConnected: () => {{
    client.publishSnapshot({{ sessionId: "session-1", isStreaming: false, messages: [] }});
    client.publishEvent("input", {{ text: "CLI prompt", origin: "local" }});
    void client.requestApproval({{
      turnId: "turn-1",
      toolCallId: "tool-1",
      toolName: "bash",
      preview: "Tool: bash",
    }}).then((value) => {{ approvalResult = value; }});
  }},
  onConnectionChanged: () => {{}},
}});
client.start();
await Promise.race([done, new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 5000))]);
await new Promise((resolve) => setTimeout(resolve, 0));
client.stop();
await new Promise((resolve) => server.close(resolve));
await unlink(socketPath).catch(() => {{}});
process.stdout.write(JSON.stringify({{
  commands,
  approvalResult,
  eventTypes: received.map((record) => record.type),
}}));
"""
    result = _node_json(script)
    assert result["commands"][0]["message"] == "hello from phone"
    assert result["approvalResult"] is True
    assert "session.snapshot" in result["eventTypes"]
    assert "event.publish" in result["eventTypes"]
    assert "approval.request" in result["eventTypes"]


def test_rpc_subagent_history_is_bounded_markdown() -> None:
    script = f"""
import {{ formatTsSubagentHistoryMarkdown }} from {json.dumps(UI.as_uri())};
const records = [{{
  task_id: "sub_1",
  operation: "claim_review",
  state: "running",
  node_refs: ["node_1"],
  claim_refs: ["claim_1"],
  run_ref: "reviews/claim_1/runs/sub_1",
  summary: "Independent review is running.",
  live: true,
}}];
process.stdout.write(JSON.stringify(formatTsSubagentHistoryMarkdown(records)));
"""
    markdown = _node_json(script)
    assert markdown.startswith("# TS Subagent History")
    assert "## `sub_1` · Review · running" in markdown
    assert "- Owner: `node_1`" in markdown
    assert "- Action: claim review" in markdown
    assert "> Independent review is running." in markdown


def test_phone_sdk_runtime_preserves_session_local_models() -> None:
    result = subprocess.run(
        ["node", "tests/phone-runtime.test.mjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
