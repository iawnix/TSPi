from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TSPI = ROOT / "TSPi"
PHONE_POLICY = ROOT / "extensions" / "ts-phone-bridge" / "policy.ts"
PHONE_PROTOCOL = ROOT / "extensions" / "ts-phone-bridge" / "protocol.ts"
PHONE_CLIENT = ROOT / "extensions" / "ts-phone-bridge" / "bridge-client.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def _copy_launcher(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    package_home = install_root / ".pi" / "packages" / "ts-agent"
    package_root = package_home / "releases" / "test-release"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text('{"name":"@iawnix/ts-agent","version":"0.7.0"}\n', encoding="utf-8")
    (package_root / ".ts-agent-release.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-agent-release/1",
                "release_id": "test-release",
                "package": {"name": "@iawnix/ts-agent", "version": "0.7.0"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.copy2(TSPI, package_root / "TSPi")
    (package_root / "TSPi").chmod(0o755)
    (package_root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "tspi_host.py", package_root / "scripts" / "tspi_host.py")
    for name in ("ts_runtime", "ts_validation", "ts_workspace"):
        shutil.copytree(
            ROOT / name,
            package_root / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    (package_home / "current").symlink_to("releases/test-release")
    launcher = install_root / "TSPi"
    launcher.symlink_to(".pi/packages/ts-agent/current/TSPi")
    return install_root, launcher


def test_tspi_phone_starts_visible_bridged_tui(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'mode': os.environ.get('TS_PHONE_MODE'), "
        "'workspace': os.environ.get('TS_PHONE_WORKSPACE_ID')}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    completed = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--phone"],
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
    assert "--continue" in result["args"]
    assert "--mode" not in result["args"]
    assert any(value.endswith("/extensions/ts-phone-bridge/index.ts") for value in result["args"])
    assert (install_root / "workspaces" / "reaction-phone" / ".pi" / "settings.json").is_file()


def test_tspi_phone_worker_is_removed(tmp_path: Path) -> None:
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
    assert "was removed" in rejected.stderr


def test_phone_policy_classifies_tools_and_redacts_confirmation() -> None:
    script = f"""
import {{ CONFIRMATION_REQUIRED_TOOLS, DIRECTLY_ALLOWED_TOOLS, formatConfirmation }} from {json.dumps(PHONE_POLICY.as_uri())};
const preview = formatConfirmation({{ type: "tool_call", toolCallId: "write-1", toolName: "write", input: {{ path: "result.md", token: "secret-value" }} }});
process.stdout.write(JSON.stringify({{
  read: DIRECTLY_ALLOWED_TOOLS.has("read"),
  bash: CONFIRMATION_REQUIRED_TOOLS.has("bash"),
  unknown: DIRECTLY_ALLOWED_TOOLS.has("new_tool") || CONFIRMATION_REQUIRED_TOOLS.has("new_tool"),
  preview,
}}));
"""
    result = _node_json(script)
    assert result["read"] is True
    assert result["bash"] is True
    assert result["unknown"] is False
    assert "secret-value" not in result["preview"]
    assert "[redacted]" in result["preview"]


def test_phone_bridge_protocol_rejects_raw_rpc_records() -> None:
    script = f"""
import {{ parseBridgeServerRecord }} from {json.dumps(PHONE_PROTOCOL.as_uri())};
let rawRpcError;
try {{ parseBridgeServerRecord({{ protocolVersion: "ts-phone-bridge/1", type: "prompt", message: "x" }}); }}
catch (error) {{ rawRpcError = error.message; }}
const command = parseBridgeServerRecord({{
  protocolVersion: "ts-phone-bridge/1",
  type: "command.prompt",
  workspaceId: "ts_006",
  instanceEpoch: "epoch-1",
  sessionGeneration: 2,
  requestId: "request-1",
  clientMessageId: "client-1",
  message: "hello",
}});
process.stdout.write(JSON.stringify({{ rawRpcError, command }}));
"""
    result = _node_json(script)
    assert result["rawRpcError"]
    assert result["command"]["message"] == "hello"


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
        protocolVersion: "ts-phone-bridge/1",
        workspaceId: "ts_006",
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
  socketPath,
  secretPath: {json.dumps(str(secret_path))},
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
  task_id: "sub_review-1",
  operation: "claim_review",
  state: "running",
  act_refs: ["act_probe"],
  claim_refs: ["clm_probe"],
  run_ref: "acts/act_probe/agent-runs/sub_review-1",
  summary: "Independent review is running.",
  live: true,
}}];
process.stdout.write(JSON.stringify(formatTsSubagentHistoryMarkdown(records)));
"""
    markdown = _node_json(script)
    assert markdown.startswith("# TS Review History")
    assert "## Review · claim\\_review" in markdown
    assert "`sub_review-1`" in markdown
    assert "`act_probe`" in markdown
    assert "> Independent review is running." in markdown


def test_rpc_activity_widget_uses_serializable_string_lines() -> None:
    script = f"""
import installUi from {json.dumps(UI.as_uri())};
const handlers = {{}};
const listeners = new Map();
const pi = {{
  on: (name, handler) => {{ handlers[name] = handler; }},
  registerEntryRenderer: () => {{}},
  registerCommand: () => {{}},
  getThinkingLevel: () => "high",
  events: {{
    on: (channel, listener) => {{
      const values = listeners.get(channel) || new Set();
      values.add(listener);
      listeners.set(channel, values);
      return () => values.delete(listener);
    }},
  }},
}};
installUi(pi);
const widgets = [];
const ctx = {{
  mode: "rpc",
  cwd: "/tmp/tspi-phone-rpc",
  ui: {{
    setWidget: (key, content, options) => widgets.push({{ key, content, options }}),
    setWorkingMessage: () => {{}},
  }},
}};
await handlers.session_start({{ type: "session_start", reason: "startup" }}, ctx);
await handlers.tool_execution_start({{
  type: "tool_execution_start",
  toolCallId: "render-1",
  toolName: "ts_render",
  args: {{ operation: "compare", actId: "act_probe", outputName: "compare.png" }},
}}, ctx);
const active = widgets.findLast((item) => Array.isArray(item.content));
await handlers.session_shutdown({{ type: "session_shutdown", reason: "quit" }}, ctx);
process.stdout.write(JSON.stringify(active));
"""
    widget = _node_json(script)
    assert widget["key"] == "ts-activity"
    assert widget["options"] == {"placement": "aboveEditor"}
    assert isinstance(widget["content"], list)
    assert widget["content"]
    assert all(isinstance(line, str) for line in widget["content"])
    assert "TS Activity" in widget["content"][0]
    assert "Render" in "\n".join(widget["content"])


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
