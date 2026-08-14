from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TSPI = ROOT / "TSPi"
PHONE_POLICY = ROOT / "extensions" / "ts-phone-policy" / "index.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def _copy_launcher(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    launcher = install_root / "TSPi"
    package_root = install_root / ".pi" / "git" / "github.com" / "iawnix" / "TSAgentSkill"
    package_root.mkdir(parents=True)
    shutil.copy2(TSPI, launcher)
    launcher.chmod(0o755)
    return install_root, launcher


def test_tspi_phone_control_opens_one_registered_workspace(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    phone_ctl = tmp_path / "ts-phone-ctl"
    phone_ctl.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
    phone_ctl.chmod(0o755)

    completed = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--phone"],
        cwd=install_root,
        env={**os.environ, "TS_PHONE_CTL": str(phone_ctl), "PI_BIN": "/missing/pi"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "open reaction-phone"
    assert (install_root / "workspaces" / "reaction-phone" / ".pi" / "settings.json").is_file()


def test_tspi_phone_worker_is_internal_and_loads_rpc_policy(tmp_path: Path) -> None:
    install_root, launcher = _copy_launcher(tmp_path)
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    rejected = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--phone-worker"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert rejected.returncode == 2
    assert "reserved for the TS Phone service" in rejected.stderr

    started = subprocess.run(
        [str(launcher), "--workspace", "reaction-phone", "--phone-worker"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi), "TS_PHONE_MODE": "research"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    args = json.loads(started.stdout)
    assert "--mode" in args and args[args.index("--mode") + 1] == "rpc"
    assert "--continue" in args
    assert "--phone-worker" not in args
    assert any(value.endswith("/extensions/ts-phone-policy/index.ts") for value in args)


def test_phone_policy_confirms_mutations_and_fails_closed() -> None:
    script = f"""
import installPolicy, {{ formatConfirmation }} from {json.dumps(PHONE_POLICY.as_uri())};
process.env.TS_PHONE_MODE = "research";
let handler;
const pi = {{ on: (name, value) => {{ if (name === "tool_call") handler = value; }} }};
installPolicy(pi);
const decisions = [false, true];
const confirmations = [];
const ctx = {{ ui: {{ confirm: async (title, message, options) => {{
  confirmations.push({{ title, message, options }});
  return decisions.shift();
}} }} }};
const allowed = await handler({{ type: "tool_call", toolCallId: "read-1", toolName: "read", input: {{ path: "README.md" }} }}, ctx);
const unknown = await handler({{ type: "tool_call", toolCallId: "new-1", toolName: "new_tool", input: {{}} }}, ctx);
const compute = await handler({{ type: "tool_call", toolCallId: "compute-1", toolName: "ts_subagent_compute", input: {{ operation: "submit", apiKey: "secret-value" }} }}, ctx);
const bash = await handler({{ type: "tool_call", toolCallId: "bash-1", toolName: "bash", input: {{ command: "pwd" }} }}, ctx);
const preview = formatConfirmation({{ type: "tool_call", toolCallId: "write-1", toolName: "write", input: {{ path: "result.md", token: "secret-value" }} }});
process.stdout.write(JSON.stringify({{
  allowed: allowed === undefined,
  unknown,
  compute,
  bash: bash === undefined,
  confirmations,
  preview,
}}));
"""
    result = _node_json(script)
    assert result["allowed"] is True
    assert result["unknown"]["block"] is True
    assert result["compute"]["block"] is True
    assert result["bash"] is True
    assert len(result["confirmations"]) == 2
    assert result["confirmations"][0]["options"]["timeout"] == 300_000
    assert "secret-value" not in result["confirmations"][0]["message"]
    assert "secret-value" not in result["preview"]
    assert "[redacted]" in result["preview"]


def test_rpc_subagent_history_is_bounded_markdown() -> None:
    script = f"""
import {{ formatTsSubagentHistoryMarkdown }} from {json.dumps(UI.as_uri())};
const records = [{{
  task_id: "agent-1",
  role: "backend",
  operation: "submit",
  state: "running",
  node_ids: ["n003"],
  backend: "gaussian",
  run_ref: "nodes/n003/agent-runs/agent-1",
  summary: "Remote calculation is queued.",
  live: true,
}}];
process.stdout.write(JSON.stringify(formatTsSubagentHistoryMarkdown(records)));
"""
    markdown = _node_json(script)
    assert markdown.startswith("# TS Subagent History")
    assert "## Compute · submit" in markdown
    assert "`agent-1`" in markdown
    assert "`n003`" in markdown
    assert "> Remote calculation is queued." in markdown


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
  toolName: "ts_subagent_render",
  args: {{ operation: "compare", nodeId: "n009" }},
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
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
