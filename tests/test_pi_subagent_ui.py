from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "extensions" / "shared" / "subagent-status.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
SESSION_LIFECYCLE = ROOT / "src" / "agent-core" / "session-lifecycle.cjs"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_status_reporter_emits_versioned_phases_and_classifies_terminal_errors() -> None:
    script = f"""
import {{ createSubagentStatusReporter, isTsSubagentStatus, terminalStatusForError }} from {json.dumps(STATUS.as_uri())};
const updates = [];
const report = createSubagentStatusReporter({{
  tool_call_id: "call-1",
  task_id: "agent-1",
  role: "backend",
  operation: "submit",
  backend: "gaussian",
  node_id: "n003",
  intent_id: "calc_n003_maleic",
}}, (partial) => updates.push(partial.details));
for (const phase of ["preflight", "starting", "running", "validating", "completed"]) report(phase);
const timeout = Object.assign(new Error("late"), {{ code: "TS_SUBAGENT_TIMEOUT" }});
const abort = Object.assign(new Error("stop"), {{ code: "TS_SUBAGENT_ABORTED" }});
const observerFailure = createSubagentStatusReporter({{ tool_call_id: "call-2", task_id: "agent-2", role: "review", operation: "mechanism" }}, () => {{ throw new Error("ui failed"); }})("running");
process.stdout.write(JSON.stringify({{
  updates,
  valid: updates.every(isTsSubagentStatus),
  timeout: terminalStatusForError(timeout),
  abort: terminalStatusForError(abort),
  failure: terminalStatusForError(new Error("boom")),
  observerFailure,
}}));
"""
    result = _node_json(script)
    assert result["valid"] is True
    assert [item["phase"] for item in result["updates"]] == [
        "preflight",
        "starting",
        "running",
        "validating",
        "completed",
    ]
    assert all(item["schema_version"] == "ts-subagent-status/1" for item in result["updates"])
    assert result["timeout"] == {"phase": "failed", "failure_kind": "timeout"}
    assert result["abort"] == {"phase": "cancelled", "failure_kind": "aborted"}
    assert result["failure"] == {"phase": "failed", "failure_kind": "error"}
    assert result["observerFailure"]["phase"] == "running"


def test_session_lifecycle_reports_child_creation_and_validation_in_order() -> None:
    script = f"""
import {{ createRequire }} from "node:module";
const require = createRequire(import.meta.url);
const helper = require({json.dumps(str(SESSION_LIFECYCLE))});
const phases = [];
const onLifecycle = (phase) => phases.push(phase);
const session = {{
  prompt: async () => undefined,
  abort: async () => undefined,
  dispose: () => phases.push("disposed"),
}};
await helper.withDisposableSession(
  async () => ({{ session }}),
  async (created) => helper.promptWithDeadline(created.session, "review", {{ timeoutMs: 1000, onLifecycle }}),
  {{ onLifecycle }},
);
process.stdout.write(JSON.stringify(phases));
"""
    assert _node_json(script) == ["starting", "running", "validating", "disposed"]


def test_ui_reducer_handles_success_timeout_abort_failure_and_widths() -> None:
    script = f"""
import {{ createTsSubagentUiState, pruneTsSubagentUiState, reduceTsSubagentUiState, renderTsSubagentPanel }} from {json.dumps(UI.as_uri())};
const state = createTsSubagentUiState();
const args = {{ operation: "submit", backend: "gaussian", nodeId: "n003", intentId: "calc_n003_maleic" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_start", toolCallId: "call-1", toolName: "ts_subagent_compute", args }}, 1000);
const running = {{ schema_version: "ts-subagent-status/1", tool_call_id: "call-1", task_id: "agent-1", role: "backend", operation: "submit", phase: "running", backend: "gaussian", node_id: "n003", intent_id: "calc_n003_maleic" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: running }} }}, 2000);
const active = state.runs.get("call-1");
const panels = [8, 60, 100, 140].map((width) => ({{ width, lines: renderTsSubagentPanel(active, width, 19000) }}));
reduceTsSubagentUiState(state, {{ type: "tool_execution_end", toolCallId: "call-1", toolName: "ts_subagent_compute", result: {{}}, isError: false }}, 20000);
const completed = state.runs.get("call-1").status.phase;
const timeout = {{ ...running, phase: "failed", failure_kind: "timeout" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: timeout }} }}, 21000);
const timeoutPhase = state.runs.get("call-1").status;
const abort = {{ ...running, phase: "cancelled", failure_kind: "aborted" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: abort }} }}, 22000);
const abortPhase = state.runs.get("call-1").status;
reduceTsSubagentUiState(state, {{ type: "tool_execution_start", toolCallId: "call-2", toolName: "ts_subagent_review", args: {{ reviewType: "connectivity", nodeId: "n006" }} }}, 23000);
reduceTsSubagentUiState(state, {{ type: "tool_execution_end", toolCallId: "call-2", toolName: "ts_subagent_review", result: {{}}, isError: true }}, 24000);
const failed = state.runs.get("call-2").status.phase;
const prunedEarly = pruneTsSubagentUiState(state, 26499);
const prunedLate = pruneTsSubagentUiState(state, 26500);
process.stdout.write(JSON.stringify({{ panels, completed, timeoutPhase, abortPhase, failed, prunedEarly, prunedLate, remaining: state.runs.size }}));
"""
    result = _node_json(script)
    for panel in result["panels"]:
        assert len(panel["lines"]) == 2
        assert all(len(line) <= panel["width"] for line in panel["lines"])
        if panel["width"] >= 60:
            assert panel["lines"][0].endswith("00:18")
            assert panel["lines"][1] == "Gaussian · submit · n003 · calc_n003_maleic"
    assert result["completed"] == "completed"
    assert result["timeoutPhase"]["failure_kind"] == "timeout"
    assert result["abortPhase"]["phase"] == "cancelled"
    assert result["failed"] == "failed"
    assert result["prunedEarly"] is True  # call-1 expired first
    assert result["prunedLate"] is True   # call-2 expires at the boundary
    assert result["remaining"] == 0


def test_ui_extension_is_observational_and_registers_history_renderers() -> None:
    script = f"""
import installUi from {json.dumps(UI.as_uri())};
const handlers = {{}};
const renderers = [];
let registeredTools = 0;
const pi = {{
  on: (name, handler) => {{ handlers[name] = handler; }},
  registerEntryRenderer: (name) => renderers.push(name),
  registerTool: () => registeredTools++,
}};
installUi(pi);
const calls = [];
const ui = {{
  setStatus: (...args) => calls.push(["status", ...args]),
  setWidget: (...args) => calls.push(["widget", ...args]),
}};
const ctx = {{ ui }};
const args = {{ operation: "compare", nodeId: "n009" }};
await handlers.tool_execution_start({{ type: "tool_execution_start", toolCallId: "call", toolName: "ts_subagent_render", args }}, ctx);
await handlers.tool_execution_update({{ type: "tool_execution_update", toolCallId: "call", toolName: "ts_subagent_render", args, partialResult: {{ details: {{ schema_version: "ts-subagent-status/1", tool_call_id: "call", task_id: "agent", role: "render", operation: "compare", phase: "running", node_id: "n009" }} }} }}, ctx);
await handlers.tool_execution_end({{ type: "tool_execution_end", toolCallId: "call", toolName: "ts_subagent_render", result: {{}}, isError: false }}, ctx);
await handlers.session_shutdown({{ type: "session_shutdown" }}, ctx);
process.stdout.write(JSON.stringify({{
  handlerNames: Object.keys(handlers).sort(),
  renderers: renderers.sort(),
  registeredTools,
  statuses: calls.filter((item) => item[0] === "status").map((item) => item[2]),
  widgets: calls.filter((item) => item[0] === "widget").length,
}}));
"""
    result = _node_json(script)
    assert result["registeredTools"] == 0
    assert result["handlerNames"] == [
        "session_shutdown",
        "tool_execution_end",
        "tool_execution_start",
        "tool_execution_update",
    ]
    assert result["renderers"] == sorted(
        [
            "ts-workspace-subagent-run",
            "ts-workspace-subagent-failed",
            "ts-workspace-compute-operator-run",
            "ts-workspace-compute-operator-failed",
            "ts-workspace-artifact-operator-run",
            "ts-workspace-artifact-operator-failed",
        ]
    )
    assert any(value and "running" in value for value in result["statuses"])
    assert result["statuses"][-1] is None
    assert result["widgets"] >= 4


def test_all_five_public_subagent_tools_emit_status_updates() -> None:
    review = (ROOT / "extensions" / "ts-workflow-review" / "index.ts").read_text(encoding="utf-8")
    compute = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    artifacts = (ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts").read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    assert review.count("createSubagentStatusReporter({") == 1
    assert compute.count("createSubagentStatusReporter({") == 1
    assert artifacts.count("createSubagentStatusReporter({") == 3
    for source in (review, compute, artifacts):
        assert "reportStatus(\"preflight\")" in source
        assert "onLifecycle: reportStatus" in source
        assert "reportStatus(\"completed\"" in source
        assert "terminalStatusForError(error)" in source
    assert "setHeader" not in ui
    assert "setFooter" not in ui
    assert "setEditorComponent" not in ui
    assert "setTitle" not in ui
    assert "registerTool" not in ui


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
