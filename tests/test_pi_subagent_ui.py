from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "extensions" / "shared" / "subagent-status.ts"
ICONS = ROOT / "extensions" / "shared" / "icons.ts"
TOOL_PRESENTATION = ROOT / "extensions" / "shared" / "subagent-tool-presentation.ts"
PROFILE = ROOT / "extensions" / "shared" / "package-profile.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
ACTIVITY_STORE = ROOT / "extensions" / "ts-workflow-ui" / "activity-store.ts"
ACTIVITY_PANEL = ROOT / "extensions" / "ts-workflow-ui" / "activity-panel.ts"
DETAILS = ROOT / "extensions" / "ts-workflow-ui" / "agent-details.ts"
SUBAGENT_HISTORY = ROOT / "extensions" / "ts-workflow-ui" / "subagent-history.ts"
EDITOR = ROOT / "extensions" / "ts-workflow-ui" / "editor.ts"
RENDER_UTILS = ROOT / "extensions" / "ts-workflow-ui" / "render-utils.ts"
STARTUP = ROOT / "extensions" / "ts-workflow-ui" / "startup.ts"
COMPUTE = ROOT / "extensions" / "ts-workflow-compute" / "index.ts"
THEME = ROOT / "themes" / "ts-theme.json"
SESSION_LIFECYCLE = ROOT / "src" / "agent-core" / "session-lifecycle.cjs"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_status_reporter_emits_versioned_states_and_classifies_terminal_results() -> None:
    script = f"""
import {{
  createSubagentStatusReporter,
  isTsSubagentStatus,
  terminalStateForReport,
  terminalStatusForError,
}} from {json.dumps(STATUS.as_uri())};
const updates = [];
let tick = 0;
const report = createSubagentStatusReporter({{
  tool_call_id: "call-1",
  task_id: "agent-1",
  role: "backend",
  operation: "submit",
  backend: "gaussian",
  node_id: "n003",
  intent_id: "calc_n003_maleic",
}}, (partial) => updates.push(partial.details), () => new Date(1000 + tick++ * 1000));
for (const state of ["queued", "starting", "running", "waiting", "validating", "completed"]) {{
  report(state, state === "waiting" ? {{ wait_reason: "model_response" }} : undefined);
}}
const timeout = Object.assign(new Error("late"), {{ code: "TS_SUBAGENT_TIMEOUT" }});
const abort = Object.assign(new Error("stop"), {{ code: "TS_SUBAGENT_ABORTED" }});
const observerFailure = createSubagentStatusReporter({{ tool_call_id: "call-2", task_id: "agent-2", role: "review", operation: "mechanism" }}, () => {{ throw new Error("ui failed"); }})("running");
process.stdout.write(JSON.stringify({{
  updates,
  valid: updates.every(isTsSubagentStatus),
  invalidWaitReason: isTsSubagentStatus({{ ...updates[3], state: "running" }}),
  timeout: terminalStatusForError(timeout),
  abort: terminalStatusForError(abort),
  failure: terminalStatusForError(new Error("boom")),
  terminalStates: [
    terminalStateForReport({{ outcome: "success" }}),
    terminalStateForReport({{ outcome: "partial" }}),
    terminalStateForReport({{ outcome: "failure" }}),
    terminalStateForReport({{ outcome: "not_run" }}),
  ],
  observerFailure,
}}));
"""
    result = _node_json(script)
    assert result["valid"] is True
    assert result["invalidWaitReason"] is False
    assert [item["state"] for item in result["updates"]] == [
        "queued",
        "starting",
        "running",
        "waiting",
        "validating",
        "completed",
    ]
    assert [item["seq"] for item in result["updates"]] == list(range(1, 7))
    assert len({item["started_at"] for item in result["updates"]}) == 1
    assert len({item["updated_at"] for item in result["updates"]}) == 6
    assert result["updates"][3]["wait_reason"] == "model_response"
    assert all("wait_reason" not in item for item in result["updates"] if item["state"] != "waiting")
    assert all(item["schema_version"] == "ts-subagent-status/2" for item in result["updates"])
    assert result["timeout"] == {"state": "failed", "failure_kind": "timeout"}
    assert result["abort"] == {"state": "cancelled", "failure_kind": "aborted"}
    assert result["failure"] == {"state": "failed", "failure_kind": "error"}
    assert result["terminalStates"] == ["completed", "partial", "failed", "failed"]
    assert result["observerFailure"]["state"] == "running"


def test_session_lifecycle_reports_child_creation_and_validation_in_order() -> None:
    script = f"""
import {{ createRequire }} from "node:module";
const require = createRequire(import.meta.url);
const helper = require({json.dumps(str(SESSION_LIFECYCLE))});
const states = [];
const onLifecycle = (state, update) => states.push({{ state, ...update }});
const session = {{
  prompt: async () => undefined,
  abort: async () => undefined,
  dispose: () => states.push({{ state: "disposed" }}),
}};
await helper.withDisposableSession(
  async () => ({{ session }}),
  async (created) => helper.promptWithDeadline(created.session, "review", {{ timeoutMs: 1000, onLifecycle }}),
  {{ onLifecycle }},
);
process.stdout.write(JSON.stringify(states));
"""
    assert _node_json(script) == [
        {"state": "starting"},
        {"state": "running"},
        {"state": "waiting", "wait_reason": "model_response"},
        {"state": "validating"},
        {"state": "disposed"},
    ]


def test_icon_styles_and_subagent_tool_presentation_are_compact_and_auditable() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{ tspiIcon, tspiIconLabel, tspiIconStyle }} from {json.dumps(ICONS.as_uri())};
import {{ renderTsSubagentCall, renderTsSubagentResult }} from {json.dumps(TOOL_PRESENTATION.as_uri())};
const theme = {{ fg: (_color, text) => text }};
const args = {{ backend: "gaussian", operation: "submit", nodeId: "n003", intentId: "calc_n003" }};
const call = renderTsSubagentCall("compute", args, theme).render(100);
const result = {{
  content: [{{ type: "text", text: '{{"outcome":"partial","summary":"receipt unknown"}}' }}],
  details: {{ report: {{ outcome: "partial" }}, run: {{ run_ref: "nodes/n003/agent-runs/agent_1" }} }},
}};
const collapsed = renderTsSubagentResult("compute", result, {{ expanded: false, isPartial: false }}, theme, false).render(100);
const expanded = renderTsSubagentResult("compute", result, {{ expanded: true, isPartial: false }}, theme, false).render(100);
const failed = renderTsSubagentResult("review", {{
  content: [{{ type: "text", text: '{{"outcome":"failure"}}' }}],
  details: {{ result: {{ outcome: "failure" }} }},
}}, {{ expanded: false, isPartial: false }}, theme, false).render(100);
const notRun = renderTsSubagentResult("report", {{
  content: [{{ type: "text", text: '{{"outcome":"not_run"}}' }}],
  details: {{ report: {{ outcome: "not_run" }} }},
}}, {{ expanded: false, isPartial: false }}, theme, false).render(100);
process.env.TSPI_ICON_STYLE = "unicode";
process.stdout.write(JSON.stringify({{
  defaults: [tspiIcon("running", "nerd"), tspiIcon("roleCompute", "nerd")],
  unicode: [tspiIcon("running"), tspiIcon("roleCompute")],
  unicodeStyle: tspiIconStyle(),
  label: tspiIconLabel("cwd", "~/workspace"),
  widths: [tspiIcon("running", "nerd"), tspiIcon("roleCompute", "nerd")].map(visibleWidth),
  call, collapsed, expanded, failed, notRun,
}}));
"""
    result = _node_json(script)
    assert result["unicodeStyle"] == "unicode"
    assert result["unicode"] == ["●", "◆"]
    assert result["label"] == "▣ ~/workspace"
    assert result["widths"] == [1, 1]
    assert "Compute" in "\n".join(result["call"])
    assert "n003" in "\n".join(result["call"])
    assert "partial" in "\n".join(result["collapsed"])
    assert "receipt unknown" not in "\n".join(result["collapsed"])
    assert "receipt unknown" in "\n".join(result["expanded"])
    assert "failed" in "\n".join(result["failed"])
    assert result["failed"][0].lstrip().startswith("")
    assert result["notRun"][0].lstrip().startswith("")


def test_activity_store_tracks_subagents_and_remote_without_state_regression() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{
  createTsActivityStore,
  pruneTsActivities,
  reducePublishedTsActivity,
  reduceTsSubagentActivity,
  sortedTsActivities,
  summarizeTsActivities,
}} from {json.dumps(ACTIVITY_STORE.as_uri())};
import {{ renderTsActivityPanel }} from {json.dumps(ACTIVITY_PANEL.as_uri())};
const store = createTsActivityStore();
const iso = (value) => new Date(value).toISOString();
const start = (call, toolName, args, now) => reduceTsSubagentActivity(store, {{ type: "tool_execution_start", toolCallId: call, toolName, args }}, now);
const update = (call, toolName, status, now) => reduceTsSubagentActivity(store, {{ type: "tool_execution_update", toolCallId: call, toolName, args: {{}}, partialResult: {{ details: status }} }}, now);
const status = (call, task, role, operation, stateName, seq, now, extra = {{}}) => ({{
  schema_version: "ts-subagent-status/2", seq, tool_call_id: call, task_id: task, role, operation,
  state: stateName, started_at: iso(now - 1000), updated_at: iso(now), ...extra,
}});

start("compute", "ts_subagent_compute", {{ operation: "submit", backend: "gaussian", nodeId: "n003", intentId: "calc_n003" }}, 1000);
update("compute", "ts_subagent_compute", status("compute", "agent-compute", "backend", "submit", "running", 1, 2000, {{ backend: "gaussian", node_id: "n003", intent_id: "calc_n003" }}), 2000);
const staleIgnored = !update("compute", "ts_subagent_compute", status("compute", "agent-compute", "backend", "submit", "waiting", 1, 2500, {{ wait_reason: "model_response" }}), 2500);
const duplicateStartIgnored = !start("compute", "ts_subagent_compute", {{}}, 2600);

start("review", "ts_subagent_review", {{ targetClaimRef: "claim_path_001", nodeIds: ["n006"] }}, 2000);
update("review", "ts_subagent_review", status("review", "agent-review", "review", "claim_review", "waiting", 1, 3000, {{ node_id: "n006", target_ref: "claim_path_001", wait_reason: "model_response" }}), 3000);
start("report", "ts_subagent_report", {{ operation: "build", packageRef: "reports/n002" }}, 3000);
update("report", "ts_subagent_report", status("report", "agent-report", "report", "build", "completed", 1, 4000, {{ target_ref: "reports/n002" }}), 4000);
start("render", "ts_subagent_render", {{ operation: "compare", nodeId: "n009" }}, 4000);
update("render", "ts_subagent_render", status("render", "agent-render", "render", "compare", "failed", 1, 5000, {{ node_id: "n009", failure_kind: "error" }}), 5000);

const terminalAccepted = update("compute", "ts_subagent_compute", status("compute", "agent-compute", "backend", "submit", "partial", 2, 6000, {{ backend: "gaussian", node_id: "n003" }}), 6000);
const terminalRegressionIgnored = !update("compute", "ts_subagent_compute", status("compute", "agent-compute", "backend", "submit", "running", 3, 7000, {{ backend: "gaussian", node_id: "n003" }}), 7000);
reducePublishedTsActivity(store, {{ type: "upsert", activity: {{
  kind: "remote", id: "remote:doctor", mode: "doctor", state: "running",
  detail: "Read-only · full control-path health", startedAt: 7000, updatedAt: 7000,
}} }});
const panels = [32, 40, 60, 100, 140].map((width) => {{
  const lines = renderTsActivityPanel(store, width, 8000, 4, "unicode");
  return {{ width, lines, widths: lines.map((line) => visibleWidth(line.text)) }};
}});
const ordered = sortedTsActivities(store).map((activity) => [
  activity.kind === "subagent" ? activity.status.task_id : activity.mode,
  activity.kind === "subagent" ? activity.status.state : activity.state,
]);
const summary = summarizeTsActivities(store);
const prunedEarly = pruneTsActivities(store, 18999);
const prunedLate = pruneTsActivities(store, 19000);
process.stdout.write(JSON.stringify({{
  panels, ordered, summary, staleIgnored, duplicateStartIgnored, terminalAccepted,
  terminalRegressionIgnored, terminalState: store.activities.get("subagent:compute").status.state,
  prunedEarly, prunedLate, remaining: [...store.activities.values()].map((activity) => activity.kind === "subagent" ? activity.status.state : activity.state),
}}));
"""
    result = _node_json(script)
    for panel in result["panels"]:
        assert all(width <= panel["width"] for width in panel["widths"]), panel
        assert "TS Activity" in panel["lines"][0]["text"]
        assert panel["lines"][-1]["text"].strip() == "+1 more activities"
    assert result["panels"][-1]["lines"][0]["text"].endswith("2 active · 2 attention · 1 done")
    assert result["ordered"][:2] == [["agent-compute", "partial"], ["agent-render", "failed"]]
    assert result["summary"] == {"active": 2, "attention": 2, "done": 1, "total": 5}
    assert result["staleIgnored"] is True
    assert result["duplicateStartIgnored"] is True
    assert result["terminalAccepted"] is True
    assert result["terminalRegressionIgnored"] is True
    assert result["terminalState"] == "partial"
    assert result["prunedEarly"] is False
    assert result["prunedLate"] is True
    assert sorted(result["remaining"]) == ["failed", "partial", "running", "waiting"]


def test_agent_details_merge_live_and_durable_bounded_records(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_ref = "nodes/n000/agent-runs/agent_partial"
    run_dir = workspace / run_ref
    run_dir.mkdir(parents=True)
    documents = {
        "task.json": {
            "schema_version": "ts-agent-task/2",
            "task_id": "agent_partial",
            "role": "backend",
            "operation": "parse",
        },
        "evidence-snapshot.json": {
            "schema_version": "ts-review-evidence-snapshot/2",
            "task_id": "agent_partial",
        },
        "provider-input.json": {
            "schema_version": "ts-review-provider-input/2",
            "task_id": "agent_partial",
        },
        "actions.json": {
            "schema_version": "ts-agent-actions/1",
            "task_id": "agent_partial",
            "actions": [{
                "tool": "ts_workspace_compute_parse",
                "result": {
                    "action_status": "completed",
                    "artifact_refs": ["nodes/n000/outputs/calculation_result.json"],
                },
            }],
        },
        "result.json": {
            "outcome": "partial",
            "summary": "Parser returned bounded output with one limitation.",
            "artifact_refs": ["nodes/n000/outputs/calculation_result.json"],
        },
        "run.json": {
            "status": "completed",
            "metadata": {"action_outcome": "succeeded", "program_status": "normal"},
            "error": None,
        },
    }
    for name, value in documents.items():
        (run_dir / name).write_text(json.dumps(value), encoding="utf-8")
    symlink_ref = "nodes/n000/agent-runs/agent_link"
    (run_dir.parent / "agent_link").symlink_to(run_dir, target_is_directory=True)

    report = {
        "agent_runs": [
            {
                "task_id": "agent_partial",
                "role": "backend",
                "operation": "parse",
                "status": "completed",
                "result_outcome": "partial",
                "node_ids": ["n000"],
                "run_ref": run_ref,
                "started_at": "2026-08-12T00:00:00Z",
                "finished_at": "2026-08-12T00:00:05Z",
                "summary": "Parser returned bounded output with one limitation.",
            },
            {
                "task_id": "agent_pending",
                "role": "review",
                "operation": "claim_review",
                "status": "pending",
                "node_ids": ["n006"],
                "run_ref": "nodes/n006/agent-runs/agent_pending",
            },
        ],
    }
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{ createTsActivityStore, reduceTsSubagentActivity }} from {json.dumps(ACTIVITY_STORE.as_uri())};
import {{
  agentSelectionLabel,
  collectTsAgentRecords,
  readTsAgentRunDocuments,
  renderTsAgentDetails,
}} from {json.dumps(DETAILS.as_uri())};
const state = createTsActivityStore();
reduceTsSubagentActivity(state, {{
  type: "tool_execution_start", toolCallId: "live-call", toolName: "ts_subagent_review",
  args: {{ targetClaimRef: "claim_path_001", nodeIds: ["n003"] }},
}}, 1000);
const live = {{
  schema_version: "ts-subagent-status/2", seq: 1, tool_call_id: "live-call", task_id: "agent_live",
  role: "review", operation: "claim_review", state: "running", node_id: "n003", target_ref: "claim_path_001",
  started_at: "2026-08-12T00:00:01Z", updated_at: "2026-08-12T00:00:02Z",
}};
reduceTsSubagentActivity(state, {{
  type: "tool_execution_update", toolCallId: "live-call", toolName: "ts_subagent_review", args: {{}},
  partialResult: {{ details: live }},
}}, 2000);
const records = collectTsAgentRecords(state, {json.dumps(report)});
const partial = records.find((record) => record.task_id === "agent_partial");
const docs = readTsAgentRunDocuments({json.dumps(str(workspace))}, partial.run_ref);
const details = renderTsAgentDetails(partial, docs, 52, Date.parse("2026-08-12T00:00:06Z"));
const failures = [];
for (const ref of ["../agent_partial", {json.dumps(symlink_ref)}]) {{
  try {{ readTsAgentRunDocuments({json.dumps(str(workspace))}, ref); }} catch (error) {{ failures.push(error.message); }}
}}
process.stdout.write(JSON.stringify({{
  records, labels: records.map(agentSelectionLabel), documentNames: Object.keys(docs), details,
  widths: details.map(visibleWidth), failures,
}}));
"""
    result = _node_json(script)
    assert [record["state"] for record in result["records"]] == ["partial", "unknown", "running"]
    assert [record["live"] for record in result["records"]] == [False, False, True]
    assert all(label.split(" · ")[-2] in {"partial", "running", "unknown"} for label in result["labels"])
    assert result["documentNames"] == [
        "task", "evidenceSnapshot", "providerInput", "actions", "result", "run"
    ]
    assert max(result["widths"]) <= 52
    rendered = "\n".join(result["details"])
    for expected in (
        "Subagent Run Details · Compute",
        "Parser returned bounded output",
        "ts_workspace_compute_parse · completed",
        "nodes/n000/outputs/calculation_result.json",
        "task.json, evidence-snapshot.json,",
        "provider-input.json, actions.json,",
        "run.json",
    ):
        assert expected in rendered
    assert len(result["failures"]) == 2
    assert "invalid TS agent run reference" in result["failures"][0]
    assert "invalid TS agent run directory" in result["failures"][1]


def test_subagent_history_browser_pages_records_and_details_by_identity() -> None:
    script = f"""
import {{ KeybindingsManager, TUI_KEYBINDINGS, visibleWidth }} from "@earendil-works/pi-tui";
import {{ SubagentHistoryBrowser }} from {json.dumps(SUBAGENT_HISTORY.as_uri())};
const records = Array.from({{ length: 17 }}, (_, index) => ({{
  task_id: `agent_${{String(index).padStart(2, "0")}}_sharedxx`,
  role: "review",
  operation: "connectivity",
  state: "completed",
  node_ids: ["n006"],
  run_ref: `nodes/n006/agent-runs/agent_${{String(index).padStart(2, "0")}}`,
  live: false,
}}));
const theme = {{
  fg: (_color, text) => text,
  bg: (_color, text) => text,
  bold: (text) => text,
}};
let renderRequests = 0;
let closed = 0;
const reads = [];
const warnings = [];
const browser = new SubagentHistoryBrowser({{
  records,
  workspaceRoot: "/tmp/workspace",
  tui: {{ requestRender: () => renderRequests++ }},
  theme,
  keybindings: new KeybindingsManager(TUI_KEYBINDINGS),
  done: () => closed++,
  notifyWarning: (message) => warnings.push(message),
  readDocuments: (_root, runRef) => {{
    reads.push(runRef);
    if (runRef.endsWith("agent_16")) throw new Error("journal unavailable");
    return {{
      result: {{
        summary: Array.from({{ length: 24 }}, (_, value) => `Review detail ${{value}}`).join("\\n"),
      }},
    }};
  }},
}});
const views = [];
const capture = (name, width = 52) => {{
  const lines = browser.render(width);
  views.push({{ name, lines, widths: lines.map(visibleWidth), snapshot: browser.getSnapshot() }});
}};
capture("initial");
browser.handleInput("\\u001b[B");
browser.handleInput("\\u001b[A");
browser.handleInput("\\u001b[6~");
capture("page2");
browser.handleInput("\\u001b[6~");
capture("page3");
browser.handleInput("\\u001b[5~");
browser.handleInput("\\u001b[H");
browser.handleInput("\\r");
capture("detail1");
browser.handleInput("\\u001b[6~");
capture("detail2");
browser.handleInput("\\u001b");
browser.handleInput("\\u001b[F");
browser.handleInput("\\r");
capture("missingJournal");
browser.handleInput("\\u001b");
browser.handleInput("\\u001b");
process.stdout.write(JSON.stringify({{ views, reads, warnings, renderRequests, closed }}));
"""
    result = _node_json(script)
    views = {view["name"]: view for view in result["views"]}

    assert views["initial"]["snapshot"]["listPageCount"] == 3
    assert views["initial"]["snapshot"]["selectedTaskId"] == "agent_00_sharedxx"
    assert views["page2"]["snapshot"]["selectedIndex"] == 8
    assert views["page2"]["snapshot"]["listPage"] == 1
    assert "Page 2/3" in "\n".join(views["page2"]["lines"])
    assert views["page3"]["snapshot"]["selectedIndex"] == 16
    assert views["page3"]["snapshot"]["listPage"] == 2
    assert len(views["page3"]["lines"]) == len(views["initial"]["lines"])

    assert views["detail1"]["snapshot"]["mode"] == "details"
    assert views["detail1"]["snapshot"]["selectedTaskId"] == "agent_00_sharedxx"
    assert views["detail1"]["snapshot"]["detailPageCount"] >= 2
    assert views["detail2"]["snapshot"]["detailPage"] == 1
    assert "Subagent Run Details" in views["detail1"]["lines"][0]

    assert result["reads"] == [
        "nodes/n006/agent-runs/agent_00",
        "nodes/n006/agent-runs/agent_16",
    ]
    assert result["warnings"] == ["journal unavailable"]
    assert views["missingJournal"]["snapshot"]["selectedTaskId"] == "agent_16_sharedxx"
    assert "agent_16_sharedxx" in "\n".join(views["missingJournal"]["lines"])
    assert max(width for view in result["views"] for width in view["widths"]) <= 52
    assert result["renderRequests"] >= 12
    assert result["closed"] == 1


def test_tspi_startup_profile_matches_package_manifest() -> None:
    script = f"""
import {{ TS_PACKAGE_PROFILE }} from {json.dumps(PROFILE.as_uri())};
process.stdout.write(JSON.stringify(TS_PACKAGE_PROFILE));
"""
    profile = _node_json(script)
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert profile["version"] == manifest["version"]
    assert [profile["skill"]["path"]] == manifest["pi"]["skills"]
    assert [item["path"] for item in profile["extensions"]] == manifest["pi"]["extensions"]
    assert [profile["theme"]["path"]] == manifest["pi"]["themes"]


def test_tspi_startup_render_is_compact_and_width_safe() -> None:
    script = f"""
import {{ createTspiStartupHeader, renderTspiStartupLines }} from {json.dumps(STARTUP.as_uri())};
import {{ visibleWidth }} from "@earendil-works/pi-tui";
const widths = [18, 40, 47, 60, 80, 100, 140];
const details = {{
  notificationDisplayTarget: "researcher@example.org",
  remoteDisplayTarget: "cluster-login · Torque",
  remoteConfigured: true,
  modelLabel: "openai/gpt-5",
  thinkingLabel: "high thinking",
}};
const rendered = widths.map((width) => {{
  const lines = renderTspiStartupLines("/home/iaw/TS-pi-agent", width, details);
  return {{ width, lines, lineWidths: lines.map(visibleWidth) }};
}});
const fallback = renderTspiStartupLines("/home/iaw/TS-pi-agent", 140);
const blockColors = [];
const theme = {{
  fg: (color, text) => {{ if (text.includes("█")) blockColors.push(color); return text; }},
  bold: (text) => text,
}};
const pi = {{ getThinkingLevel: () => "high" }};
const ctx = {{ ui: {{ theme }}, cwd: "/home/iaw/TS-pi-agent", model: {{ provider: "openai", id: "gpt-5" }} }};
let renderRequests = 0;
const tui = {{ terminal: {{ rows: 30 }}, requestRender: () => renderRequests++ }};
process.env.TS_REMOTE_CONFIG = "/tmp/remote.toml";
process.env.TS_REMOTE_DISPLAY_TARGET = "cluster-login · Torque";
process.env.TS_NOTIFICATION_DISPLAY_TARGET = "researcher@example.org";
const header = createTspiStartupHeader(pi, ctx, tui, "/home/iaw/TS-pi-agent");
const initial = header.render(100).join("\\n").split("█").length;
await new Promise((resolve) => setTimeout(resolve, 120));
const next = header.render(100).join("\\n").split("█").length;
header.dispose();
const liveHeader = header.render(140);
process.stdout.write(JSON.stringify({{ rendered, fallback, blockColors, initial, next, liveHeader, renderRequests }}));
"""
    result = _node_json(script)
    rendered = result["rendered"]

    for view in rendered[1:]:
        assert 6 <= len(view["lines"]) <= 16
        assert all(line_width <= view["width"] for line_width in view["lineWidths"])
        assert view["lines"][0].startswith("╭")
        assert "TSπ" in view["lines"][0]
        assert view["lines"][-1].startswith("╰")
        assert all(line.endswith(("╮", "╯", "│")) for line in view["lines"])

    assert rendered[0]["lines"] == ["TSπ TSPi"]
    assert rendered[0]["lineWidths"] == [8]

    compact = next(view["lines"] for view in rendered if view["width"] == 60)
    assert not any("█" in line for line in compact)
    assert any("TSπ" in line for line in compact)

    single_column = next(view["lines"] for view in rendered if view["width"] == 47)
    assert len([line for line in single_column if "█" in line]) == 7
    assert not any("Workspace" in line for line in single_column)

    standard = next(view["lines"] for view in rendered if view["width"] == 80)
    assert any("1 skill · 5 extensions" in line for line in standard)
    assert any("1 theme" in line for line in standard)
    assert not any("…" in line for line in standard if "skill" in line or "theme" in line)

    wide = rendered[-1]["lines"]
    pixel_lines = [line for line in wide if "█" in line]
    assert len(pixel_lines) == 7
    assert all("■" not in line for line in pixel_lines)
    assert any("██████████    ██████████    ██████████████" in line for line in pixel_lines)
    assert pixel_lines[-1].split("│")[1].strip() == "██        ██████████    ████      ████"
    assert not any("TSPi" in line for line in wide)
    assert any("Evidence-driven transition-state workflow." in line for line in wide)
    assert any("openai/gpt-5 · high thinking" in line for line in wide)
    assert not any("Workspace" in line for line in wide)
    assert any("Remote configured" in line for line in wide)
    assert any("cluster-login · Torque" in line for line in wide)
    assert any("Email · researcher@example.org" in line for line in wide)
    assert any("researcher@example.org" in line for line in wide)
    assert any("not configured" in line for line in result["fallback"])
    assert any("cluster-login · Torque" in line for line in result["liveHeader"])
    assert any("1 skill · 5 extensions" in line for line in wide)
    assert any("1 theme" in line for line in wide)
    assert not any("ts-theme" in line for line in wide)
    for command in ("/ts-context", "/ts-validate", "/ts-remote", "/ts-subagent-history"):
        assert any(command in line for line in wide)
    assert "mdLink" in result["blockColors"]
    assert result["next"] > result["initial"]
    assert result["renderRequests"] >= 1


def test_tspi_editor_replaces_default_borders_with_width_safe_rounded_frame() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{ applyTspiRoundedEditorBorders, tspiEditorMode }} from {json.dumps(EDITOR.as_uri())};
const rendered = [12, 40].map((width) => {{
  const lines = applyTspiRoundedEditorBorders(["─".repeat(width), "  input", "─".repeat(width)], width, (value) => value, "COMMAND");
  return {{ width, lines, widths: lines.map(visibleWidth) }};
}});
const modes = ["hello", "/model", "!pwd"].map(tspiEditorMode);
process.stdout.write(JSON.stringify({{ rendered, modes }}));
"""
    result = _node_json(script)
    rendered = result["rendered"]

    for view in rendered:
        assert view["widths"] == [view["width"]] * 3
        assert view["lines"][0].startswith("╭") and view["lines"][0].endswith("╮")
        assert view["lines"][1].startswith("  input") and view["lines"][1].endswith("│")
        assert view["lines"][2].startswith("╰") and view["lines"][2].endswith("╯")
    assert "COMMAND" in rendered[-1]["lines"][0]
    assert result["modes"] == [
        {"label": "", "marker": ">", "color": "accent"},
        {"label": "COMMAND", "marker": ":", "color": "warning"},
        {"label": "BASH", "marker": "$", "color": "bashMode"},
    ]


def test_mypi_render_mechanics_cover_columns_cursor_and_path_compaction() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{
  cursorOpenFromFgAnsi,
  formatCwd,
  headerColumnWidths,
  restyleEditorCursor,
  twoColumn,
}} from {json.dumps(RENDER_UTILS.as_uri())};
const narrow = headerColumnWidths(50);
const wide = headerColumnWidths(110);
const columns = twoColumn("left", "right", wide.leftWidth, wide.rightWidth, (value) => value);
const open = cursorOpenFromFgAnsi("\u001b[38;2;125;196;181m");
const cursor = restyleEditorCursor("value \u001b[7mX\u001b[0m", open);
process.stdout.write(JSON.stringify({{
  narrow,
  wide,
  columnsWidth: visibleWidth(columns),
  cwd: formatCwd("/home/iaw/TS-pi-agent", "/home/iaw"),
  open,
  cursor,
}}));
"""
    result = _node_json(script)
    assert result["narrow"] == {"leftWidth": 50, "rightWidth": 0, "useRightColumn": False}
    assert result["wide"]["useRightColumn"] is True
    assert result["columnsWidth"] == 110
    assert result["cwd"] == "~/TS-pi-agent"
    assert "\x1b[48;2;125;196;181m" in result["open"]
    assert "\x1b[7m" not in result["cursor"]
    assert f'{result["open"]}X' in result["cursor"]


def test_ts_theme_inherits_mypi_dark_palette() -> None:
    theme = json.loads(THEME.read_text(encoding="utf-8"))
    assert theme["name"] == "ts-theme"
    assert theme["vars"] == {
        "bg": "#171B24",
        "fg": "#C8D3DC",
        "accent": "#7DC4B5",
        "cyan": "#7DCFFF",
        "blue": "#7AA2F7",
        "green": "#9ECE6A",
        "red": "#F7768E",
        "yellow": "#E0AF68",
        "violet": "#BB9AF7",
        "orange": "#FF9E64",
        "operator": "#89DDFF",
        "muted": "#8292A2",
        "dimmed": "#5F6B78",
        "border": "#53697E",
        "borderMuted": "#3B4A59",
        "selectedBg": "#293746",
        "userMessageBg": "#263348",
        "customMessageBg": "#202832",
        "toolPendingBg": "#332F25",
        "toolSuccessBg": "#253229",
        "toolErrorBg": "#38282E",
    }
    assert theme["colors"]["thinkingMedium"] == "blue"
    assert theme["colors"]["mdListBullet"] == "accent"


def test_ui_extension_is_observational_and_registers_history_renderers() -> None:
    script = f"""
import installUi from {json.dumps(UI.as_uri())};
const handlers = {{}};
const renderers = [];
const commands = {{}};
let registeredTools = 0;
const eventListeners = new Map();
const pi = {{
  on: (name, handler) => {{ handlers[name] = handler; }},
  registerEntryRenderer: (name) => renderers.push(name),
  registerCommand: (name, command) => {{ commands[name] = command; }},
  registerTool: () => registeredTools++,
  getThinkingLevel: () => "high",
  events: {{
    emit: (channel, data) => eventListeners.get(channel)?.forEach((listener) => listener(data)),
    on: (channel, listener) => {{
      const listeners = eventListeners.get(channel) || new Set();
      listeners.add(listener);
      eventListeners.set(channel, listeners);
      return () => listeners.delete(listener);
    }},
  }},
}};
installUi(pi);
const calls = [];
let footerFactory;
const theme = {{ fg: (_color, text) => text, bold: (text) => text }};
const widgetLines = [];
const ui = {{
  theme,
  setStatus: (...args) => calls.push(["status", ...args]),
  setWidget: (key, content, options) => {{
    calls.push(["widget", key, typeof content, options]);
    if (typeof content === "function") widgetLines.push(content(null, theme).render(100));
  }},
  setHeader: (...args) => calls.push(["header", ...args]),
  setFooter: (factory) => {{ footerFactory = factory; calls.push(["footer", factory]); }},
  setEditorComponent: (...args) => calls.push(["editor", ...args]),
  setWorkingIndicator: (...args) => calls.push(["indicator", ...args]),
  setWorkingMessage: (...args) => calls.push(["working", ...args]),
  setTitle: (...args) => calls.push(["title", ...args]),
}};
const ctx = {{
  ui,
  mode: "tui",
  cwd: "/home/iaw/TS-pi-agent",
  model: {{ id: "gpt-5" }},
  getContextUsage: () => ({{ percent: 42 }}),
  sessionManager: {{
    getSessionName: () => "maleic-ts",
    getSessionId: () => "1234567890abcdef",
    getSessionFile: () => "/tmp/session.jsonl",
  }},
}};
let renderRequests = 0;
const tui = {{ requestRender: () => renderRequests++, terminal: {{ rows: 30 }} }};
const footerData = {{
  getGitBranch: () => "pi_ts_subagents",
  getExtensionStatuses: () => new Map([["third-party", "external: ready"]]),
  onBranchChange: () => () => {{}},
}};
const args = {{ operation: "compare", nodeId: "n009" }};
await handlers.session_start({{ type: "session_start", reason: "startup" }}, ctx);
const footer = footerFactory(tui, theme, footerData);
const initialFooter = footer.render(100)[0];
await handlers.agent_start({{ type: "agent_start" }}, ctx);
await handlers.tool_execution_start({{ type: "tool_execution_start", toolCallId: "call", toolName: "ts_subagent_render", args }}, ctx);
await handlers.tool_execution_update({{ type: "tool_execution_update", toolCallId: "call", toolName: "ts_subagent_render", args, partialResult: {{ details: {{ schema_version: "ts-subagent-status/2", seq: 1, tool_call_id: "call", task_id: "agent", role: "render", operation: "compare", state: "running", started_at: "2026-08-12T00:00:00Z", updated_at: "2026-08-12T00:00:01Z", node_id: "n009" }} }} }}, ctx);
const activeFooter = [50, 100, 140].map((width) => footer.render(width)[0]);
const activeWorking = calls.filter((item) => item[0] === "working").at(-1)?.[1];
await handlers.tool_execution_end({{ type: "tool_execution_end", toolCallId: "call", toolName: "ts_subagent_render", result: {{}}, isError: false }}, ctx);
await handlers.agent_settled({{ type: "agent_settled" }}, ctx);
const idleFooter = footer.render(100)[0];
await handlers.session_start({{ type: "session_start", reason: "switch" }}, ctx);
const switchedFooter = footer.render(100)[0];
await handlers.session_shutdown({{ type: "session_shutdown" }}, ctx);
footer.dispose();
process.stdout.write(JSON.stringify({{
  handlerNames: Object.keys(handlers).sort(),
  renderers: renderers.sort(),
  commands: Object.keys(commands),
  registeredTools,
  statuses: calls.filter((item) => item[0] === "status").map((item) => item[2]),
  widgets: calls.filter((item) => item[0] === "widget").length,
  headers: calls.filter((item) => item[0] === "header").length,
  footers: calls.filter((item) => item[0] === "footer").length,
  editors: calls.filter((item) => item[0] === "editor").length,
  titles: calls.filter((item) => item[0] === "title").map((item) => item[1]),
  working: calls.filter((item) => item[0] === "working").map((item) => item[1]),
  activeWorking,
  initialFooter,
  activeFooter,
  idleFooter,
  switchedFooter,
  widgetLines,
  renderRequests,
}}));
"""
    result = _node_json(script)
    assert result["registeredTools"] == 0
    assert result["commands"] == ["ts-subagent-history"]
    assert result["handlerNames"] == [
        "agent_settled",
        "agent_start",
        "model_select",
        "session_before_compact",
        "session_compact",
        "session_info_changed",
        "session_shutdown",
        "session_start",
        "thinking_level_select",
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
    assert result["statuses"] == []
    assert result["widgets"] >= 4
    assert result["headers"] == 3
    assert result["footers"] == 3
    assert result["editors"] == 3
    assert len(result["titles"]) == 2 and all(title.startswith("TSPi · ") for title in result["titles"])
    assert "TSPi · thinking" in result["working"][0]
    assert "TSPi · coordinating agents" in result["activeWorking"]
    assert result["working"][-1] is None
    assert result["activeFooter"][1] == result["initialFooter"]
    assert all("external: ready" not in line for line in result["activeFooter"])
    assert all(" active" not in line.lower() and " tools" not in line.lower() for line in result["activeFooter"])
    assert result["idleFooter"] == result["initialFooter"]
    assert "Render" not in result["switchedFooter"]
    assert any("TS Activity" in lines[0] and any("Render" in line for line in lines) for lines in result["widgetLines"])
    assert result["renderRequests"] >= 4


def test_real_pi_loader_shares_remote_activity_between_compute_and_ui_extensions() -> None:
    script = f"""
import {{ createEventBus }} from "@earendil-works/pi-coding-agent";
import {{ pathToFileURL }} from "node:url";
const loader = await import(pathToFileURL({json.dumps(str(ROOT / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "core" / "extensions" / "loader.js"))}).href);
const loaded = await loader.loadExtensions([
  {json.dumps(str(UI))},
  {json.dumps(str(COMPUTE))},
], {json.dumps(str(ROOT))}, createEventBus());
if (loaded.errors.length) throw new Error(JSON.stringify(loaded.errors));
const uiExtension = loaded.extensions.find((extension) => extension.resolvedPath.endsWith("/ts-workflow-ui/index.ts"));
const computeExtension = loaded.extensions.find((extension) => extension.resolvedPath.endsWith("/ts-workflow-compute/index.ts"));
const widgets = [];
const working = [];
const ctx = {{
  mode: "tui",
  cwd: "/tmp/tspi-loader-smoke",
  model: {{ id: "gpt-5" }},
  signal: new AbortController().signal,
  getContextUsage: () => ({{ percent: 10 }}),
  sessionManager: {{
    getSessionName: () => "loader-smoke",
    getSessionId: () => "1234567890abcdef",
    getSessionFile: () => "/tmp/loader-smoke.jsonl",
  }},
  ui: {{
    theme: {{ fg: (_color, text) => text }},
    select: async () => undefined,
    notify: () => {{}},
    setWidget: (key, content) => {{
      if (typeof content === "function") widgets.push(content(null, {{ fg: (_color, text) => text }}).render(100));
    }},
    setHeader: () => {{}},
    setFooter: () => {{}},
    setEditorComponent: () => {{}},
    setWorkingIndicator: () => {{}},
    setWorkingMessage: (message) => working.push(message),
    setTitle: () => {{}},
  }},
}};
await uiExtension.handlers.get("session_start")[0]({{ type: "session_start", reason: "startup" }}, ctx);
process.env.TS_AGENT_PYTHON = "/definitely/not/an/executable";
let failure;
try {{
  await computeExtension.commands.get("ts-remote").handler("status", ctx);
}} catch (error) {{
  failure = error.message;
}}
await uiExtension.handlers.get("session_shutdown")[0]({{ type: "session_shutdown", reason: "quit" }}, ctx);
process.stdout.write(JSON.stringify({{ widgets, working, failure }}));
"""
    result = _node_json(script)
    activity_panels = [lines for lines in result["widgets"] if lines and "TS Activity" in lines[0]]
    assert len(activity_panels) == 2
    assert "Remote" in "\n".join(activity_panels[0])
    assert "failed" in "\n".join(activity_panels[1])
    assert "TS_AGENT_PYTHON is not executable" in result["failure"]


def test_all_four_public_subagent_tools_emit_status_updates() -> None:
    review = (ROOT / "extensions" / "ts-workflow-review" / "index.ts").read_text(encoding="utf-8")
    compute = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    artifacts = (ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts").read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    assert review.count("createSubagentStatusReporter({") == 1
    assert compute.count("createSubagentStatusReporter({") == 1
    assert artifacts.count("createSubagentStatusReporter({") == 2
    for source in (review, compute, artifacts):
        assert "reportStatus(\"queued\")" in source
        assert "onLifecycle: reportStatus" in source
        assert "terminalStateForReport" in source
        assert "terminalStatusForError(error)" in source
        assert 'renderShell: "self"' in source
        assert "renderTsSubagentCall" in source
        assert "renderTsSubagentResult" in source
    assert "setHeader" in ui
    assert "setFooter" in ui
    assert "setEditorComponent" in ui
    assert "setTitle" in ui
    assert "setWorkingMessage" in ui
    assert 'registerCommand("ts-subagent-history"' in ui
    assert 'registerCommand("ts-agents"' not in ui
    assert "registerTool" not in ui
    for extension in (ROOT / "extensions").glob("ts-workflow-*/index.ts"):
        assert "setStatus(" not in extension.read_text(encoding="utf-8")


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
